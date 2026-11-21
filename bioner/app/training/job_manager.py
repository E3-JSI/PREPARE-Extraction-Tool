from collections import OrderedDict
import logging
import threading
from enum import Enum
from typing import Dict, Optional

from app.core.settings import settings
from app.training.gliner_trainer import GLiNERFinetuner

logger = logging.getLogger(__name__)

# Statuses that mean a job has finished and no longer holds the GPU slot.
# Anything NOT in this set (idle/pending/running) is treated as active.
_TERMINAL_STATUSES = ("completed", "failed", "stopped")
_TERMINAL_CACHE_SIZE = 20
# When a new run arrives while a previous run is still winding down after a stop
# request, join its worker thread for at most this long before giving up and
# reporting the slot as still busy (STOPPING). Kept short so the API stays
# responsive; the caller/frontend retries once the previous run has wound down.
# Sourced from settings so deployments can tune it via TRAINING_STOP_JOIN_TIMEOUT.
JOIN_TIMEOUT_SECONDS = settings.TRAINING_STOP_JOIN_TIMEOUT


class StartResult(str, Enum):
    """Outcome of a :meth:`TrainingJobManager.start_job` attempt."""

    STARTED = "started"  # new run accepted and its worker launched
    BUSY = "busy"  # another run is genuinely active (not stop-requested)
    STOPPING = "stopping"  # a stopped run hasn't wound down yet — retry shortly


class TrainingJobManager:
    """Singleton managing GLiNER fine-tuning jobs. One active job at a time."""

    _instance: Optional["TrainingJobManager"] = None
    _class_lock = threading.Lock()

    # Contains only jobs whose worker has not completely finished yet.
    _jobs: Dict[int, GLiNERFinetuner]
    _threads: Dict[int, threading.Thread]
    _jobs_lock: threading.Lock

    # Small status snapshots for the most recently finished jobs.
    _terminal_snapshots: "OrderedDict[int, dict]"

    def __new__(cls) -> "TrainingJobManager":
        with cls._class_lock:
            if cls._instance is None:
                instance = super().__new__(cls)
                instance._jobs = {}
                instance._threads = {}
                instance._jobs_lock = threading.Lock()
                instance._terminal_snapshots = OrderedDict()
                cls._instance = instance
        return cls._instance

    def start_job(
        self,
        run_id: int,
        base_model_path: str,
        labels: list[str],
        training_data: list[dict],
        eval_data: Optional[list[dict]] = None,
        device: str = "cpu",
        num_epochs: int = 4,
        learning_rate: float = 5e-6,
        train_batch_size: int = 8,
        val_ratio: float = 0.2,
        use_train_eval_split: bool = True,
    ) -> StartResult:
        # Manual lock management: we must RELEASE the lock while joining a
        # winding-down worker (so status polls / stop calls aren't blocked) and
        # re-acquire before reserving the slot.
        self._jobs_lock.acquire()
        try:
            active = self._active_locked()
            if active:
                existing = active[0]

                # Genuinely running (user didn't stop it) — reject as busy.
                if not existing._stop_event.is_set():
                    logger.warning(
                        f"Training job {run_id} rejected — "
                        f"job {existing.run_id} already active"
                    )
                    return StartResult.BUSY

                # The active job was stop-requested but its worker hasn't reached
                # a terminal status yet. Join the worker to let it wind down.
                # Release the lock across the join so other calls aren't blocked;
                # NEVER hold _jobs_lock across a join (deadlock risk).
                thread = self._threads.get(existing.run_id)
                self._jobs_lock.release()
                try:
                    if thread is not None:
                        thread.join(timeout=JOIN_TIMEOUT_SECONDS)
                finally:
                    self._jobs_lock.acquire()

                if thread is not None and thread.is_alive():
                    logger.warning(
                        f"Training job {run_id} rejected — job {existing.run_id} "
                        f"still stopping after {JOIN_TIMEOUT_SECONDS}s"
                    )
                    return StartResult.STOPPING

                # A concurrent start_job may have claimed the slot while we had
                # released the lock to join. Re-check before reserving.
                still_active = self._active_locked()
                if still_active:
                    other = still_active[0]
                    logger.warning(
                        f"Training job {run_id} rejected — "
                        f"job {other.run_id} active"
                    )
                    return (
                        StartResult.STOPPING
                        if other._stop_event.is_set()
                        else StartResult.BUSY
                    )

            finetuner = GLiNERFinetuner(
                run_id=run_id,
                base_model_path=base_model_path,
                labels=labels,
                training_data=training_data,
                eval_data=eval_data,
                device=device,
                num_epochs=num_epochs,
                learning_rate=learning_rate,
                train_batch_size=train_batch_size,
                val_ratio=val_ratio if use_train_eval_split else 0.0,
            )

            # Reserve the slot BEFORE releasing the lock: mark as running now so a
            # concurrent start_job sees this job as active. The worker thread sets
            # it to "running" again under _status_lock, which is harmless.
            finetuner._status = "running"
            self._terminal_snapshots.pop(run_id, None)
            self._jobs[run_id] = finetuner

            def _run():
                try:
                    finetuner.run()
                finally:
                    self._finish_job(run_id, finetuner)
                    logger.info(f"Training job {run_id} done")

            t = threading.Thread(
                target=_run,
                name=f"gliner-train-{run_id}",
                daemon=False,
            )
            self._threads[run_id] = t

            try:
                t.start()
            except BaseException:
                self._jobs.pop(run_id, None)
                self._threads.pop(run_id, None)
                raise

            logger.info(f"Training job {run_id} started on device={device}")
            return StartResult.STARTED
        finally:
            self._jobs_lock.release()

    def get_status(self, run_id: int) -> Optional[dict]:
        with self._jobs_lock:
            job = self._jobs.get(run_id)
            terminal = self._terminal_snapshots.get(run_id)

            if job is None:
                return dict(terminal) if terminal is not None else None

        return job.get_snapshot()

    def stop_job(self, run_id: int) -> bool:
        with self._jobs_lock:
            job = self._jobs.get(run_id)

        if not job or job._status in _TERMINAL_STATUSES:
            return False

        job.request_stop()

        # Force immediate UI update
        job._emit({
            "type": "stopped",
            "run_id": run_id,
        })

        return True

    def _active_locked(self) -> list[GLiNERFinetuner]:
        """Return workers that have not completely finished cleanup yet."""
        return list(self._jobs.values())

    def _terminal_snapshot(self, job: GLiNERFinetuner) -> dict:
        """Keep only the small part of a completed job needed by status calls."""
        status = job._status
        error = getattr(job, "_error", None)

        if status not in _TERMINAL_STATUSES:
            status = "failed"
            error = error or "Training worker exited unexpectedly."

        return {
            "status": status,
            "new_events": [],
            "output_path": getattr(job, "_output_path", None),
            "error": error,
        }

    def _finish_job(self, run_id: int, job: GLiNERFinetuner) -> None:
        """Replace a finished finetuner with a lightweight status snapshot."""
        snapshot = self._terminal_snapshot(job)

        with self._jobs_lock:
            if self._jobs.get(run_id) is not job:
                return

            self._jobs.pop(run_id, None)
            self._threads.pop(run_id, None)

            self._terminal_snapshots[run_id] = snapshot
            self._terminal_snapshots.move_to_end(run_id)

            while len(self._terminal_snapshots) > _TERMINAL_CACHE_SIZE:
                self._terminal_snapshots.popitem(last=False)


def get_training_job_manager() -> TrainingJobManager:
    return TrainingJobManager()
