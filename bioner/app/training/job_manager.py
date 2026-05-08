import logging
import threading
from typing import Optional

from app.training.gliner_trainer import GLiNERFinetuner

logger = logging.getLogger(__name__)


class TrainingJobManager:
    """Singleton managing GLiNER fine-tuning jobs. Enforces one active job at a time."""

    _instance: Optional["TrainingJobManager"] = None
    _class_lock = threading.Lock()

    def __new__(cls) -> "TrainingJobManager":
        with cls._class_lock:
            if cls._instance is None:
                instance = super().__new__(cls)
                instance._jobs: dict[int, GLiNERFinetuner] = {}
                instance._jobs_lock = threading.Lock()
                cls._instance = instance
        return cls._instance

    def start_job(
        self,
        run_id: int,
        base_model_path: str,
        training_data: list[dict],
        device: str = "cpu",
        num_epochs: int = 4,
        learning_rate: float = 5e-6,
        train_batch_size: int = 8,
        val_ratio: float = 0.2,
    ) -> bool:
        """
        Start a training job. Returns False if a job is already running.
        Always unloads the inference model before training (RAM is finite on CPU).
        Restores pre-training model state when training completes.
        """
        from app.model_manager import get_model_manager

        with self._jobs_lock:
            active = [j for j in self._jobs.values() if j._status == "running"]
            if active:
                logger.warning(f"Training job {run_id} rejected — job {active[0].run_id} already running")
                return False

            mm = get_model_manager()
            # Capture state, unload model, write training_active flag — all atomically
            saved_state = mm.set_training_active(True)

            finetuner = GLiNERFinetuner(
                run_id=run_id,
                base_model_path=base_model_path,
                training_data=training_data,
                device=device,
                num_epochs=num_epochs,
                learning_rate=learning_rate,
                train_batch_size=train_batch_size,
                val_ratio=val_ratio,
            )
            self._jobs[run_id] = finetuner

            def _run_with_cleanup() -> None:
                try:
                    finetuner.run()
                finally:
                    # Restore pre-training inference state so workers auto-reload
                    get_model_manager().set_training_active(False, pre_training_state=saved_state)
                    logger.info(f"Training job {run_id} done — inference state restored")
                    self._prune_old_jobs()

            t = threading.Thread(
                target=_run_with_cleanup, daemon=True, name=f"gliner-train-{run_id}"
            )
            t.start()
            logger.info(f"Training job {run_id} started on device={device}")
            return True

    def get_status(self, run_id: int) -> Optional[dict]:
        """Return status snapshot for a job. Drains its event buffer."""
        with self._jobs_lock:
            job = self._jobs.get(run_id)
        if job is None:
            return None
        return job.get_snapshot()

    def stop_job(self, run_id: int) -> bool:
        """Request graceful stop of an active job."""
        with self._jobs_lock:
            job = self._jobs.get(run_id)
        if job and job._status == "running":
            job.request_stop()
            return True
        return False

    def _prune_old_jobs(self, keep_last: int = 20) -> None:
        with self._jobs_lock:
            done = [
                (rid, j)
                for rid, j in self._jobs.items()
                if j._status in ("completed", "failed", "stopped")
            ]
            for rid, _ in done[:-keep_last]:
                del self._jobs[rid]


def get_training_job_manager() -> TrainingJobManager:
    return TrainingJobManager()
