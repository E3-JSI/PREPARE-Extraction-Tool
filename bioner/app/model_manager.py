import gc
import json
import logging
import os
import tempfile
import threading
from typing import Optional, Any
from pathlib import Path
from datetime import datetime

import torch

from app.engines import build_engine
from app.interfaces import ModelInfo, ModelHealthCheck, AvailableModel, AvailableModelsResponse

logger = logging.getLogger(__name__)


class ModelManager:
    _instance: Optional['ModelManager'] = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._initialized = True
        self._switch_lock = threading.RLock()
        self._model_instance: Optional[Any] = None
        self._current_engine: Optional[str] = None
        self._current_model_path: Optional[str] = None
        self._current_adapter_model: Optional[str] = None
        self._current_prompt_path: Optional[str] = None
        self._current_device: Optional[str] = None
        self._use_gpu: bool = False
        self._is_loading: bool = False
        self._load_error: Optional[str] = None
        self._load_start_time: Optional[datetime] = None
        
        # State file sync for cross-process model switching
        self._state_path = os.environ.get(
            "BIONER_MODEL_STATE_PATH",
            os.path.join(tempfile.gettempdir(), "bioner_model_state.json")
        )
        self._last_state_mtime_ns: int = 0  # Initialize to 0 so first state file is detected as changed

    def switch_model(self,
                    engine: str,
                    model: str,
                    adapter_model: Optional[str] = None,
                    prompt_path: Optional[str] = None,
                    use_gpu: bool = False) -> ModelInfo:
        """Switch model by writing state file. Worker auto-loads via get_model()."""
        with self._switch_lock:
            try:
                logger.info(f"Starting model switch: engine={engine}, model={model}")
                
                # Validate input
                if not engine or not model:
                    raise ValueError("engine and model must be specified")
                
                # Update metadata locally
                self._current_engine = engine
                self._current_model_path = model
                self._current_adapter_model = adapter_model
                self._current_prompt_path = prompt_path
                self._use_gpu = use_gpu
                
                # Write state file for workers to detect
                self._write_state()
                
                # If we already have a model loaded (worker process), reload it now
                # Otherwise (API process), just signal the worker via state file
                if self._model_instance is not None:
                    self._is_loading = True
                    self._load_error = None
                    self._load_start_time = datetime.now()
                    self._unload_model()
                    self._load_from_state_file()

                logger.info(f"Model switch signaled: {engine} - {model}")
                return self.get_model_info()

            except Exception as e:
                self._is_loading = False
                self._load_error = str(e)
                logger.error(f"Failed to switch model: {e}", exc_info=True)
                raise ValueError(f"Failed to switch model: {str(e)}")

    def _get_model_device(self, model_instance: Any) -> Optional[str]:
        device = getattr(model_instance, "device", None)
        if device is not None:
            return str(device)

        model = getattr(model_instance, "model", None)
        if model is not None:
            model_device = getattr(model, "device", None)
            if model_device is not None:
                return str(model_device)

        return None

    def _unload_model(self) -> None:
        try:
            model_instance = self._model_instance
            device = self._current_device

            if model_instance is not None:
                model = getattr(model_instance, "model", None)
                if model is not None and hasattr(model, "to"):
                    try:
                        model.to("cpu")
                    except Exception as e:
                        logger.debug(f"Could not move model to CPU: {e}")

                self._model_instance = None
                self._current_engine = None
                self._current_model_path = None
                self._current_adapter_model = None
                self._current_device = None
                self._use_gpu = False

                del model_instance
                gc.collect()

                if device == "cuda" and torch.cuda.is_available():
                    torch.cuda.empty_cache()

                logger.info("Model unloaded successfully")
        except Exception as e:
            logger.warning(f"Error during model unload: {e}")

    def _snapshot(self) -> dict:
        """Create snapshot of current model state for serialization."""
        return {
            "engine": self._current_engine,
            "model": self._current_model_path,
            "adapter_model": self._current_adapter_model,
            "prompt_path": self._current_prompt_path,
            "use_gpu": self._use_gpu,
        }

    def _write_state(self) -> None:
        """Write state snapshot to file (atomic write)."""
        try:
            state_dir = os.path.dirname(self._state_path)
            os.makedirs(state_dir, exist_ok=True)
            
            state = self._snapshot()
            
            # Atomic write: write to temp file, then rename
            temp_fd, temp_path = tempfile.mkstemp(dir=state_dir, text=True)
            try:
                with os.fdopen(temp_fd, 'w') as f:
                    json.dump(state, f)
                os.replace(temp_path, self._state_path)
                # Don't update _last_state_mtime_ns here - let _state_changed() detect it
                logger.debug(f"State written to {self._state_path}")
            except Exception as e:
                os.close(temp_fd)
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                raise
        except Exception as e:
            logger.error(f"Failed to write state file: {e}")
            raise

    def _read_state(self) -> Optional[dict]:
        """Read state snapshot from file."""
        try:
            if os.path.exists(self._state_path):
                with open(self._state_path, 'r') as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"Failed to read state file: {e}")
        return None

    def _state_changed(self) -> bool:
        """Check if state file has been modified since last read."""
        try:
            if not os.path.exists(self._state_path):
                return False
            
            current_mtime_ns = os.stat(self._state_path).st_mtime_ns
            changed = current_mtime_ns != self._last_state_mtime_ns
            
            if changed:
                logger.debug(f"State file changed: {self._last_state_mtime_ns} -> {current_mtime_ns}")
                self._last_state_mtime_ns = current_mtime_ns
            
            return changed
        except Exception as e:
            logger.debug(f"Error checking state file mtime: {e}")
            return False

    def _load_from_state_file(self) -> None:
        """Load model from current state file."""
        try:
            self._is_loading = True
            self._load_error = None
            self._load_start_time = datetime.now()
            
            if not self._current_engine or not self._current_model_path:
                raise ValueError("No engine or model path specified")
            
            self._model_instance = build_engine(
                engine=self._current_engine,
                model=self._current_model_path,
                adapter_model=self._current_adapter_model,
                prompt_path=self._current_prompt_path,
                use_gpu=self._use_gpu
            )
            
            self._current_device = self._get_model_device(self._model_instance)
            self._is_loading = False
            logger.info(f"Model loaded in worker: {self._current_engine} - {self._current_model_path}")
        except Exception as e:
            self._is_loading = False
            self._load_error = str(e)
            self._model_instance = None
            logger.error(f"Failed to load model from state: {e}", exc_info=True)
            raise

    def get_model(self) -> Optional[Any]:
        """Get model, auto-reloading if state file changed (worker process)."""
        with self._switch_lock:
            # Check if external process changed the model config
            if self._state_changed():
                state = self._read_state()
                if state:
                    logger.info("State file changed, reloading model in worker")
                    self._unload_model()
                    
                    # Set metadata AFTER unloading (so it doesn't get cleared by _unload_model)
                    self._current_engine = state.get("engine")
                    self._current_model_path = state.get("model")
                    self._current_adapter_model = state.get("adapter_model")
                    self._current_prompt_path = state.get("prompt_path")
                    self._use_gpu = state.get("use_gpu", False)
                    
                    self._load_from_state_file()
            
            return self._model_instance

    def get_model_info(self) -> ModelInfo:
        with self._switch_lock:
            if self._is_loading:
                status = "loading"
            elif self._load_error:
                status = "error"
            elif self._model_instance is not None:
                status = "loaded"
            else:
                status = "unloaded"

            return ModelInfo(
                engine=self._current_engine or "none",
                model_path=self._current_model_path or "none",
                adapter_model=self._current_adapter_model,
                prompt_path=self._current_prompt_path,
                use_gpu=self._use_gpu,
                device=self._current_device,
                loaded=self._model_instance is not None,
                status=status
            )

    def health_check(self) -> ModelHealthCheck:
        with self._switch_lock:
            model_info = self.get_model_info()

            if self._is_loading:
                elapsed = (datetime.now() - self._load_start_time).total_seconds()
                return ModelHealthCheck(
                    healthy=False,
                    loaded=False,
                    engine=self._current_engine,
                    message=f"Model is loading... ({elapsed:.1f}s elapsed)"
                )

            if self._load_error:
                return ModelHealthCheck(
                    healthy=False,
                    loaded=False,
                    engine=self._current_engine,
                    message=f"Model load failed: {self._load_error}"
                )

            if model_info.loaded:
                return ModelHealthCheck(
                    healthy=True,
                    loaded=True,
                    engine=self._current_engine,
                    message="Model is loaded and ready"
                )
            else:
                return ModelHealthCheck(
                    healthy=False,
                    loaded=False,
                    engine=None,
                    message="No model loaded"
                )

    def discover_available_models(self, model_base_path: str = "/model") -> AvailableModelsResponse:
        available_models: list[AvailableModel] = []

        try:
            base_path = Path(model_base_path)

            gliner_path = base_path / "gliner"
            if gliner_path.exists():
                for model_dir in gliner_path.iterdir():
                    if model_dir.is_dir():
                        available_models.append(AvailableModel(
                            name=f"GLiNER - {model_dir.name}",
                            engine="gliner",
                            path=str(model_dir),
                            type="gliner"
                        ))

            gliner2_path = base_path / "gliner2"
            if gliner2_path.exists():
                for model_dir in gliner2_path.iterdir():
                    if model_dir.is_dir():
                        available_models.append(AvailableModel(
                            name=f"GLiNER2 - {model_dir.name}",
                            engine="gliner2",
                            path=str(model_dir),
                            type="gliner2"
                        ))

            adapters_path = base_path / "adapters"
            if adapters_path.exists():
                for adapter_dir in adapters_path.iterdir():
                    if adapter_dir.is_dir():
                        available_models.append(AvailableModel(
                            name=f"LLM Adapter - {adapter_dir.name}",
                            engine="huggingface",
                            path=str(adapter_dir),
                            type="huggingface"
                        ))

            logger.info(f"Discovered {len(available_models)} available models")

        except Exception as e:
            logger.warning(f"Error discovering available models: {e}")

        return AvailableModelsResponse(models=available_models)

    def is_model_loaded(self) -> bool:
        with self._switch_lock:
            return self._model_instance is not None and not self._is_loading

    def is_loading(self) -> bool:
        with self._switch_lock:
            return self._is_loading


_model_manager: Optional[ModelManager] = None


def get_model_manager() -> ModelManager:
    global _model_manager
    if _model_manager is None:
        _model_manager = ModelManager()
    return _model_manager
