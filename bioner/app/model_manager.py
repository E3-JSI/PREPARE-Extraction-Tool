import gc
import logging
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
        self._current_device: Optional[str] = None
        self._use_gpu: bool = False
        self._is_loading: bool = False
        self._load_error: Optional[str] = None
        self._load_start_time: Optional[datetime] = None

    def switch_model(self,
                    engine: str,
                    model: str,
                    adapter_model: Optional[str] = None,
                    use_gpu: bool = False) -> ModelInfo:
        with self._switch_lock:
            try:
                logger.info(f"Starting model switch: engine={engine}, model={model}")
                self._is_loading = True
                self._load_error = None
                self._load_start_time = datetime.now()

                if self._model_instance is not None:
                    self._unload_model()

                self._model_instance = build_engine(
                    engine=engine,
                    model=model,
                    adapter_model=adapter_model,
                    prompt_path=None,
                    use_gpu=use_gpu
                )

                self._current_engine = engine
                self._current_model_path = model
                self._current_adapter_model = adapter_model
                self._current_device = self._get_model_device(self._model_instance)
                self._use_gpu = use_gpu
                self._is_loading = False

                logger.info(f"Model successfully switched to: {engine} - {model}")
                return self.get_model_info()

            except Exception as e:
                self._is_loading = False
                self._load_error = str(e)
                self._model_instance = None
                logger.error(f"Failed to switch model: {e}", exc_info=True)
                raise ValueError(f"Failed to load model: {str(e)}")

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

    def get_model(self) -> Optional[Any]:
        with self._switch_lock:
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

    def discover_available_models(self, model_base_path: str = "/app/model") -> AvailableModelsResponse:
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
