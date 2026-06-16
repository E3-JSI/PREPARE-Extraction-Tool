
import gc
import json
import logging
import os
from pathlib import Path
import tempfile
import threading
from typing import Optional, Any
from datetime import datetime, timezone

from xml.parsers.expat import model

from app.core.settings import settings as settings
from app.engines import build_engine
from app.interfaces import ModelInfo, ModelHealthCheck, AvailableModel, AvailableModelsResponse

logger = logging.getLogger(__name__)

import torch
from sqlmodel import Session, select

from app.engines import build_engine  

logger = logging.getLogger(__name__)


# -------------------------------------------------
# PROJECT PATHS
# -------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent

MODELS_DIR = PROJECT_ROOT / "models"
GLINER_MODELS_DIR = MODELS_DIR / "gliner"

RUNS_DIR = GLINER_MODELS_DIR

HF_MODELS = [
    {
        "name": "gliner_small",
        "path": settings.BIONER_DEFAULT_MODEL,
    },
    {
        "name": "medical_gliner_v2",
        "path": settings.BIONER_DEFAULT_MODEL_PVT,
    },
    ]

logger = logging.getLogger(__name__)

MODELS_DIR = PROJECT_ROOT / "models" / "gliner"

def is_hf_model(model: str) -> bool:
    return "/" in model and not os.path.isabs(model)

class ModelManager:
    _instance = None
    _lock = threading.Lock()

    @property
    def current_model_path(self):
        return self._current_model_path

    @property
    def current_engine(self):
        return self._current_engine
    # =====================================================
    # SINGLETON
    # =====================================================
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    # =====================================================
    # INIT
    # =====================================================
    def __init__(self):
        if getattr(self, "_initialized", False):
            return

        self._initialized = True

        self._switch_lock = threading.RLock()

        self._model_instance: Optional[Any] = None
        self._current_model_path: Optional[str] = None
        self._current_engine: Optional[str] = None

        # -----------------------------------------
        # TRAINING STATE
        # -----------------------------------------
        self._training_active: bool = False
        self._training_run_id: Optional[int] = None

    # =====================================================
    # CORE LOAD FUNCTION
    # =====================================================



    def switch_model(
        self,
        engine: str,
        model: str,
        adapter_model: Optional[str] = None,
        prompt_path: Optional[str] = None,
        use_gpu: bool = False,
    ):
        with self._switch_lock:
            logger.info(f"Switching model -> {engine}:{model}")
            
            # Skip path resolution for HuggingFace models
            if is_hf_model(model):
                resolved_model = model 
            else:
                # Use robust path resolution with fallback strategies
                resolved_model = self._resolve_model_path(model)
                
                if not os.path.exists(resolved_model):
                    raise ValueError(f"Model path does not exist: {resolved_model}")
            
            logger.info(f"ACTUAL MODEL PATH USED: {resolved_model}")
            logger.info(f"PATH EXISTS: {os.path.exists(resolved_model)}")
            
            self._unload_model()
            self._current_engine = engine
            self._current_model_path = resolved_model
            self._model_instance = build_engine(engine=engine, model=resolved_model, adapter_model=adapter_model, prompt_path=prompt_path, use_gpu=use_gpu,)
            logger.info("Model loaded successfully")
            return self.get_model_info()
    
    def _resolve_model_path(self, model_path: str) -> str:
        """
        Resolve model path with fallback strategies.
        
        Handles:
        - Absolute paths (Windows C:\... and Unix /path)
        - Relative paths
        - Docker mount paths (/model, /models)
        
        Resolution order:
        1. Use path if absolute and exists
        2. Find model name in GLINER_MODELS_DIR
        3. Use abspath() of input
        4. Parse path components to reconstruct location
        """
        logger.info(f"Resolving model path: {model_path}")
        
                # ✅ HuggingFace model detection
        if "/" in model_path and not os.path.isabs(model_path):
            logger.info(f"Detected HF model: {model_path}")
            return model_path  # DO NOT convert to /code/

        # Strategy 1: Absolute path that exists
        if os.path.isabs(model_path) and os.path.exists(model_path):
            return os.path.abspath(model_path)
        
        # Strategy 2: Try to find just the model name in GLINER_MODELS_DIR
        model_name = Path(model_path).name
        candidate_path = GLINER_MODELS_DIR / model_name
        
        if os.path.exists(candidate_path):
            resolved = str(candidate_path.resolve())
            logger.info(f"Found model by name in GLINER_MODELS_DIR: {resolved}")
            return resolved
        
        # Strategy 3: Use abspath as fallback
        abs_path = os.path.abspath(model_path)
        if os.path.exists(abs_path):
            logger.info(f"Found at absolute path: {abs_path}")
            return abs_path
        
        # Strategy 4: Parse and reconstruct from path components
        # Handles Docker paths like "/model/gliner/model-name" or
        # Windows paths that weren't caught above
        path_parts = Path(model_path).parts
        for i, part in enumerate(path_parts):
            if part.lower() in ("model", "models"):
                # Get remaining path components after model/models
                remaining = path_parts[i+1:]
                if remaining:
                    # Reconstruct path within GLINER_MODELS_DIR
                    candidate = GLINER_MODELS_DIR / Path(*remaining)
                    if os.path.exists(candidate):
                        resolved = str(candidate.resolve())
                        logger.info(f"Found by parsing path components: {resolved}")
                        return resolved
        
        # Nothing found, return absolute path (will fail with clear error)
        logger.warning(f"Could not resolve model path: {model_path}")
        return os.path.abspath(model_path)


    # =====================================================
    # USER MODEL LOAD
    # =====================================================
    def load_user_model(self, model_path: str):

        if not model_path:
            return self.load_default_model()

        return self.switch_model(
            engine="gliner",
            model=model_path,
        )

    # =====================================================
    # DEFAULT MODEL
    # =====================================================
    def load_default_model(self):

        default_model = os.getenv(
            "DEFAULT_MODEL",
            settings.BIONER_DEFAULT_MODEL,
        )

        return self.switch_model(
            engine="gliner",
            model=default_model,
        )

    # =====================================================
    # GET MODEL
    # =====================================================
    def get_model(self):
        return self._model_instance

    # =====================================================
    # TRAINING STATE
    # =====================================================
 
    def set_training_active(
        self,
        active: bool,
        run_id: Optional[int] = None,
        pre_training_state: Optional[dict] = None,
    ):
        """
        Manage training state and optionally restore
        pre-training inference model state.
        """

        with self._switch_lock:
            # -----------------------------------------
            # RESTORE PREVIOUS STATE AFTER TRAINING
            # -----------------------------------------
            if not active and pre_training_state:
                self._training_active = False
                self._training_run_id = None
                try:
                    previous_model = pre_training_state.get("model_path")
                    previous_engine = pre_training_state.get("engine")
                    if previous_model and previous_engine:
                        logger.info(
                            "Restoring pre-training model -> "
                            f"{previous_engine}:{previous_model}"
                        )
                        self.switch_model(
                            engine=previous_engine,
                            model=previous_model,
                        )
                except Exception as e:
                    logger.error(f"Failed restoring previous model: {e}")

                return pre_training_state

            # -----------------------------------------
            # ENABLE TRAINING MODE
            # -----------------------------------------
            previous_state = {
                "engine": self._current_engine,
                "model_path": self._current_model_path,
                "loaded": self._model_instance is not None,
            }

            self._training_active = active

            if active:
                self._training_run_id = run_id

                # unload inference model before training
                self._unload_model()

            else:
                self._training_run_id = None

            logger.info(
                "Training state changed -> "
                f"active={active}, "
                f"run_id={self._training_run_id}"
            )

            return previous_state

    def is_training_active(self) -> bool:
        return self._training_active

    def get_training_run_id(self):
        return self._training_run_id

    # =====================================================
    # UNLOAD MODEL
    # =====================================================
    def _unload_model(self):

        if self._model_instance is not None:

            logger.info("Unloading current model")

            del self._model_instance
            self._model_instance = None

            gc.collect()

            if torch.cuda.is_available():
                torch.cuda.empty_cache()

            logger.info("Model unloaded")

    # =====================================================
    # MODEL INFO
    # =====================================================
    def get_model_info(self):

        return {
            "engine": self._current_engine,
            "model_path": self._current_model_path,
            "loaded": self._model_instance is not None,
            "training_active": self._training_active,
            "training_run_id": self._training_run_id,
        }

    # =====================================================
    # DISCOVER MODELS
    # =====================================================
    def discover_available_models2(self) -> AvailableModelsResponse:
        available_models: list[AvailableModel] = []
        try:

            # -------------------------------------------------
            # 1. BUILTIN HUGGINGFACE MODELS
            # -------------------------------------------------
            for hf_model in HF_MODELS:

                available_models.append(
                    AvailableModel(
                        name=hf_model["name"],
                        engine="gliner",
                        path=hf_model["path"],
                        type="huggingface",
                    )
                )

            # -------------------------------------------------
            # 2. LOCAL TRAINED MODELS
            # -------------------------------------------------
            if os.path.exists(RUNS_DIR):

                for model_dir in os.listdir(RUNS_DIR):

                    full_path = os.path.join(
                        RUNS_DIR,
                        model_dir,
                    )

                    if os.path.isdir(full_path):

                        available_models.append(
                            AvailableModel(
                                name=model_dir,
                                engine="gliner",
                                path=full_path,
                                type="local",
                            )
                        )

            # -------------------------------------------------
            # 3. CURRENT MODEL NOT IN LIST
            # -------------------------------------------------
            current_model = self._current_model_path

            if current_model:

                exists = any(
                    m.path == current_model
                    for m in available_models
                )

                if not exists:

                    available_models.insert(
                        0,
                        AvailableModel(
                            name=os.path.basename(current_model),
                            engine="gliner",
                            path=current_model,
                            type="custom",
                        )
                    )

        except Exception as e:
            logger.error(f"Model discovery error: {e}")

        return AvailableModelsResponse(
            models=available_models,
            selected_model=self._current_model_path,
        )

    def discover_available_models(self) -> AvailableModelsResponse:
        available_models: list[AvailableModel] = []
        try:

            # -------------------------------------------------
            # 1. BUILTIN HUGGINGFACE MODELS
            # -------------------------------------------------
            for hf_model in HF_MODELS:

                available_models.append(
                    AvailableModel(
                        name=hf_model["name"],
                        engine="gliner",
                        path=hf_model["path"],
                        type="huggingface",
                    )
                )

            # -------------------------------------------------
            # 2. LOCAL TRAINED MODELS
            # -------------------------------------------------
            if os.path.exists(RUNS_DIR):

                for model_dir in os.listdir(RUNS_DIR):

                    full_path = os.path.join(
                        RUNS_DIR,
                        model_dir,
                    )

                    if os.path.isdir(full_path):

                        available_models.append(
                            AvailableModel(
                                name=model_dir,
                                engine="gliner",
                                path=full_path,
                                type="local",
                            )
                        )

            # -------------------------------------------------
            # 3. CURRENT MODEL NOT IN LIST
            # -------------------------------------------------
            current_model = self._current_model_path

            if current_model:

                exists = any(
                    m.path == current_model
                    for m in available_models
                )

                if not exists:

                    available_models.insert(
                        0,
                        AvailableModel(
                            name=os.path.basename(current_model),
                            engine="gliner",
                            path=current_model,
                            type="custom",
                        )
                    )

        except Exception as e:
            logger.error(f"Model discovery error: {e}")

        return AvailableModelsResponse(
            models=available_models,
            selected_model=self._current_model_path,
        )


# =====================================================
# GET SINGLETON INSTANCE
# =====================================================
def get_model_manager():
    return ModelManager()

 

 
