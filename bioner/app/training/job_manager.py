import logging
import threading
from typing import Optional, Dict

from app.training.gliner_trainer import GLiNERFinetuner
from app.model_manager import get_model_manager

logger = logging.getLogger(__name__)


class TrainingJobManager:
    """Singleton managing GLiNER fine-tuning jobs. One active job at a time."""

    _instance: Optional["TrainingJobManager"] = None
    _class_lock = threading.Lock()

    def __new__(cls) -> "TrainingJobManager":
        with cls._class_lock:
            if cls._instance is None:
                instance = super().__new__(cls)
                instance._jobs: Dict[int, GLiNERFinetuner] = {}
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

        with self._jobs_lock:
            active = [j for j in self._jobs.values() if j._status == "running"]
            if active:
                logger.warning(
                    f"Training job {run_id} rejected — job {active[0].run_id} already running"
                )
                return False

            mm = get_model_manager()
            saved_state = mm.set_training_active(True, run_id=run_id)

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

            def _run():
                try:
                    finetuner.run()
                finally:
                    mm.set_training_active(
                        False,
                        pre_training_state=saved_state
                    )

                    logger.info(
                        f"Training job {run_id} done — inference state restored"
                    )

                    self._prune_old_jobs()

            t = threading.Thread(
                target=_run,
                name=f"gliner-train-{run_id}",
                daemon=False,
            )
            t.start()

            logger.info(f"Training job {run_id} started on device={device}")
            return True

    def get_status(self, run_id: int) -> Optional[dict]:
        with self._jobs_lock:
            job = self._jobs.get(run_id)

        if not job:
            return None

        return job.get_snapshot()

    def stop_job(self, run_id: int) -> bool:
        with self._jobs_lock:
            job = self._jobs.get(run_id)

        if not job or job._status != "running":
            return False

        job.request_stop()

        # 🔥 FORCE immediate UI update
        job._emit({
            "type": "stopped",
            "run_id": run_id,
        })

        return True

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