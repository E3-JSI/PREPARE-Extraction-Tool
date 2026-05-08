import gc
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import torch
from gliner import GLiNER
from gliner.data_processing.collator import DataCollator
from gliner.training import Trainer, TrainingArguments
from torch.utils.data import Dataset as TorchDataset


class _RawDataset(TorchDataset):
    """Returns raw dicts so DataCollator.collate_raw_batch receives the expected format."""
    def __init__(self, data: list[dict]):
        self._data = data
    def __len__(self) -> int:
        return len(self._data)
    def __getitem__(self, idx: int) -> dict:
        return self._data[idx]

logger = logging.getLogger(__name__)


class GLiNERFinetuner:
    """Encapsulates one GLiNER fine-tuning run. Runs in a daemon thread via job_manager."""

    def __init__(
        self,
        run_id: int,
        base_model_path: str,
        training_data: list[dict],
        num_epochs: int = 4,
        learning_rate: float = 5e-6,
        train_batch_size: int = 8,
        device: str = "cpu",
    ):
        self.run_id = run_id
        self.base_model_path = base_model_path
        self.training_data = training_data
        self.num_epochs = num_epochs
        self.learning_rate = learning_rate
        self.train_batch_size = train_batch_size
        self.device = device

        self._stop_event = threading.Event()
        self._events: list[dict] = []
        self._events_lock = threading.Lock()
        self._status = "pending"
        self._output_path: Optional[str] = None
        self._error: Optional[str] = None

    def request_stop(self) -> None:
        self._stop_event.set()

    def get_snapshot(self) -> dict:
        """Drain the event buffer and return current state."""
        with self._events_lock:
            events = list(self._events)
            self._events.clear()
        return {
            "status": self._status,
            "new_events": events,
            "output_path": self._output_path,
            "error": self._error,
        }

    def _emit(self, event: dict) -> None:
        with self._events_lock:
            self._events.append(event)

    def run(self) -> None:
        """Entry point for daemon thread."""
        self._status = "running"
        try:
            self._do_train()
        except Exception as e:
            logger.error(f"Training run {self.run_id} failed: {e}", exc_info=True)
            self._status = "failed"
            self._error = str(e)
            self._emit({"type": "error", "run_id": self.run_id, "message": str(e)})
        finally:
            gc.collect()
            torch.cuda.empty_cache()  # no-op on CPU

    def _do_train(self) -> None:
        if not self.training_data:
            raise ValueError("No training examples provided")

        self._emit({
            "type": "training_info",
            "run_id": self.run_id,
            "train_size": len(self.training_data),
        })

        model = GLiNER.from_pretrained(self.base_model_path, local_files_only=False)
        model = model.to(self.device)
        logger.info(f"GLiNER model loaded on {self.device}: {self.base_model_path}")

        if self._stop_event.is_set():
            self._status = "stopped"
            return

        train_ds = _RawDataset(list(self.training_data))
        collator = DataCollator(
            model.config,
            data_processor=model.data_processor,
            prepare_labels=True,
        )

        base_name = Path(self.base_model_path).name
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = f"/model/gliner/{base_name}-finetuned-{timestamp}"

        args = TrainingArguments(
            output_dir=output_dir,
            num_train_epochs=self.num_epochs,
            per_device_train_batch_size=self.train_batch_size,
            learning_rate=self.learning_rate,
            save_strategy="no",
            fp16=False,                    # CPU default; override to True for CUDA
            use_cpu=(self.device == "cpu"),
            dataloader_num_workers=0,      # avoid fork issues in threaded context
            report_to="none",
            logging_steps=10,
        )

        finetuner = self

        class _TrackingTrainer(Trainer):
            def log(self, logs: dict, *args: Any, **kwargs: Any) -> None:
                super().log(logs, *args, **kwargs)
                if finetuner._stop_event.is_set():
                    self.control.should_training_stop = True
                numeric = {k: float(v) for k, v in logs.items() if isinstance(v, (int, float))}
                if numeric:
                    finetuner._emit({"type": "epoch_update", "run_id": finetuner.run_id, **numeric})

        trainer = _TrackingTrainer(
            model=model,
            args=args,
            train_dataset=train_ds,
            data_collator=collator,
        )

        self._emit({"type": "training_start", "run_id": self.run_id, "num_epochs": self.num_epochs})
        trainer.train()

        if self._stop_event.is_set():
            self._status = "stopped"
            return

        Path(output_dir).mkdir(parents=True, exist_ok=True)
        model.save_pretrained(output_dir)
        logger.info(f"Fine-tuned model saved to {output_dir}")

        self._output_path = output_dir
        self._status = "completed"
        self._emit({"type": "completed", "run_id": self.run_id, "output_path": output_dir})
