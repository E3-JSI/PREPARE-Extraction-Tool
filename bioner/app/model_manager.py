
import gc
import json
import logging
import os
from pathlib import Path
from pyexpat import model
import tempfile
import threading
from typing import Optional, Any
from datetime import datetime, timezone

from xml.parsers.expat import model
from ast import Load

from app.engines import build_engine
from app.interfaces import ModelInfo, ModelHealthCheck, AvailableModel, AvailableModelsResponse

logger = logging.getLogger(__name__)

# bioner/app/model_manager.py




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
        "path": "urchade/gliner_small",
    },
    {
        "name": "medical_gliner_v2",
        "path": "ErikCalcina/synthetic-multi-med-notes-ner-gliner_multi-v2.1",
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
            #if model.startswith("urchade/"):
            #    resolved_model = model
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
            "urchade/gliner_small",
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


"""
class ModelManager3:
    _instance: Optional["ModelManager3"] = None
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
        self._current_model_path: Optional[str] = None
        self._current_engine: Optional[str] = None
        self._current_device: Optional[str] = None

        self._current_user_id: Optional[int] = None

    def initialize_from_user(self, db_session, user_id: int):
        Load user's preferred model from DB on login/startup.
    
        from app.models import UserModelPreference  # IMPORTANT: inside function to avoid import issues

        pref = (
            db_session.query(UserModelPreference)
            .filter(UserModelPreference.user_id == user_id)
            .first()
        )

        if not pref:
            logger.info("No user preference found. Loading default model.")
            return self.load_default_model()

        model = pref.model  # relationship

        if not model:
            logger.warning("Preference exists but model missing. Loading default.")
            return self.load_default_model()

        logger.info(f"Loading user preferred model: {model.model_path}")

        return self.switch_model(
            engine="gliner",   # or model.engine if stored
            model=model.model_path,
            adapter_model=None,
            prompt_path=None,
            use_gpu=False
        )

    def load_default_model(self):
        default_model = os.getenv(
            "DEFAULT_MODEL",
            "urchade/gliner_small"
        )

        logger.info(f"Loading default model: {default_model}")

        return self.switch_model(
            engine="gliner",
            model=default_model,
            adapter_model=None,
            prompt_path=None,
            use_gpu=False
        )

    # =========================
    # DEVICE
    # =========================
    def _get_device(self):
        return "cuda" if torch.cuda.is_available() else "cpu"

    # =========================
    # CORE LOAD
    # =========================
    def _load_model(self, engine: str, model_path: str):
        self._model_instance = build_engine(
            engine=engine,
            model=model_path,
            adapter_model=None,
            prompt_path=None,
            use_gpu=torch.cuda.is_available()
        )

        self._current_engine = engine
        self._current_model_path = model_path
        self._current_device = self._get_device()

    # =========================
    # UNLOAD
    # =========================
    def _unload(self):
        if self._model_instance:
            del self._model_instance
            self._model_instance = None
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

    # =========================================================
    # DEFAULT MODEL (FIRST TIME ONLY)
    # =========================================================
    def load_default_model(self):
        default_engine = "gliner"
        default_model = "urchade/gliner_small"

        logger.info("Loading DEFAULT model...")
        self._unload()
        self._load_model(default_engine, default_model)

    # =========================================================
    # LOAD USER PREFERENCE FROM DB
    # =========================================================
    def initialize_from_user(self, user_id: int):
        
        Call this on login or request start.
        
        self._current_user_id = user_id

        with Session(db_engine) as session:
            stmt = select(UserModelPreference).where(
                UserModelPreference.user_id == user_id
            )
            pref = session.exec(stmt).first()

            # CASE 1: no preference → load default
            if not pref:
                logger.info(f"No preference found for user {user_id}, loading default model")
                self.load_default_model()
                return

            # CASE 2: load preferred model
            model_artifact = session.get(ModelArtifact, pref.model_id)

            if not model_artifact:
                logger.warning("ModelArtifact missing, fallback to default")
                self.load_default_model()
                return

            logger.info(f"Loading user preferred model: {model_artifact.model_path}")

            self._unload()
            self._load_model(
                engine="gliner",  # or store engine in ModelArtifact if needed
                model_path=model_artifact.model_path
            )

    # =========================================================
    # SWITCH MODEL (USER ACTION)
    # =========================================================
    def switch_model_for_user(self, user_id: int, model_id: int):
        with self._switch_lock:

            with Session(db_engine) as session:
                model_artifact = session.get(ModelArtifact, model_id)

                if not model_artifact:
                    raise ValueError("ModelArtifact not found")

                # update DB preference (UPSERT style)
                stmt = select(UserModelPreference).where(
                    UserModelPreference.user_id == user_id
                )
                pref = session.exec(stmt).first()

                if pref:
                    pref.model_id = model_id
                    pref.updated_at = datetime.now(timezone.utc)
                else:
                    pref = UserModelPreference(
                        user_id=user_id,
                        model_id=model_id
                    )
                    session.add(pref)

                session.commit()

            # switch runtime model
            logger.info(f"Switching runtime model for user {user_id}")

            self._unload()
            self._load_model(
                engine="gliner",
                model_path=model_artifact.model_path
            )

            self._current_user_id = user_id

            return {
                "status": "success",
                "model_path": model_artifact.model_path
            }

    # =========================================================
    # GET MODEL
    # =========================================================
    def get_model(self):
        return self._model_instance

    def get_model_info(self):
        return {
            "engine": self._current_engine,
            "model": self._current_model_path,
            "device": self._current_device,
            "loaded": self._model_instance is not None,
            "user_id": self._current_user_id
        }


# singleton
_model_manager: Optional[ModelManager] = None

def get_model_manager2():
    global _model_manager
    if _model_manager is None:
        _model_manager = ModelManager()
    return _model_manager





class ModelManager2:
    _instance: Optional["ModelManager2"] = None
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
        self._current_model_path: Optional[str] = None
        self._current_engine: Optional[str] = None
        self._current_device: Optional[str] = None

        self._is_loading = False
        self._load_error = None

        self._current_adapter_model = None
        self._current_prompt_path = None
        self._use_gpu = False

        self._state_path = os.path.join(MODEL_ROOT, "model_state.json")
        self._last_state_mtime_ns = 0

        self._load_start_time = None

    def _get_model_device(self, model_instance) -> str:
        try:
            if torch.cuda.is_available():
                return "cuda"
            return "cpu"
        except Exception:
            return "unknown"
    

    # =========================
    # READ LATEST MODEL
    # =========================
    def get_latest_model_path(self) -> Optional[str]:
        try:
            if not os.path.exists(LATEST_FILE):
                logger.warning("latest.json not found")
                return None

            with open(LATEST_FILE, "r") as f:
                data = json.load(f)

            return data.get("path")

        except Exception as e:
            logger.warning(f"Error during model unload: {e}")

    def _snapshot(self) -> dict:
        Create snapshot of current model state for serialization.
        return {
            "engine": self._current_engine,
            "model": self._current_model_path,
            "adapter_model": self._current_adapter_model,
            "prompt_path": self._current_prompt_path,
            "use_gpu": self._use_gpu,
        }

    def _write_state_dict(self, state: dict) -> None:
        Write arbitrary state dict to file atomically.
        try:
            state_dir = os.path.dirname(self._state_path)
            os.makedirs(state_dir, exist_ok=True)

            temp_fd, temp_path = tempfile.mkstemp(dir=state_dir, text=True)
            try:
                with os.fdopen(temp_fd, 'w') as f:
                    json.dump(state, f)
                os.replace(temp_path, self._state_path)
                logger.debug(f"State written to {self._state_path}")
            except Exception:
                os.close(temp_fd)
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                raise
        except Exception as e:
            logger.error(f"Failed to write state file: {e}")
            raise

    def _write_state(self) -> None:
        Write current model state snapshot to file.
        self._write_state_dict(self._snapshot())

    def set_training_active(self, active: bool, pre_training_state: Optional[dict] = None) -> Optional[dict]:
        
        Coordinate model unload/reload around a fine-tuning job.

        active=True:
            Captures current model state, unloads the inference model, and writes
            training_active=True to the state file so all LitServe workers free RAM.
            Returns the captured pre-training state for later restoration.

        active=False:
            Restores pre_training_state (without training_active) so workers
            auto-reload the original inference model.
        
        with self._switch_lock:
            if active:
                saved = self._snapshot()
                self._unload_model()
                self._write_state_dict({**saved, "training_active": True})
                logger.info("Training active: inference model unloaded, workers notified")
                return saved
            else:
                restore = pre_training_state or self._snapshot()
                self._write_state_dict(restore)
                logger.info("Training finished: inference state restored for workers")
                return None

    def _read_state(self) -> Optional[dict]:
        Read state snapshot from file.
        try:
            if os.path.exists(self._state_path):
                with open(self._state_path, 'r') as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"Failed to read state file: {e}")
        return None

    def _state_changed(self) -> bool:
        Check if state file has been modified since last read.
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
        Load model from current state file.
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

    # =========================
    # AUTO LOAD / HOT RELOAD
    # =========================
    def get_model(self) -> Optional[Any]:
        with self._switch_lock:
            if self._state_changed():
                state = self._read_state()
                if state:
                    # Fine-tuning in progress: yield RAM, refuse inference requests
                    if state.get("training_active"):
                        if self._model_instance is not None:
                            self._unload_model()
                        return None

                    # No model configured (e.g. immediately after training with no prior model)
                    if not state.get("engine"):
                        self._unload_model()
                        return None

                    logger.info("State file changed, reloading model in worker")
                    self._unload_model()

                    # Set metadata AFTER unloading (so it doesn't get cleared by _unload_model)
                    self._current_engine = state.get("engine")
                    self._current_model_path = state.get("model")
                    self._current_adapter_model = state.get("adapter_model")
                    self._current_prompt_path = state.get("prompt_path")
                    self._use_gpu = state.get("use_gpu", False)

                    self._load_from_state_file()
            latest_path = self.get_latest_model_path()

            if latest_path and latest_path != self._current_model_path:
                logger.info(f"🔥 New model detected: {latest_path}")

                self._unload_model()

                self._model_instance = build_engine(
                    engine="gliner",
                    model=latest_path,
                    adapter_model=None,
                    prompt_path=None,
                    use_gpu=False
                )

                self._current_model_path = latest_path
                self._current_engine = "gliner"

                logger.info("✅ Model loaded successfully")
            return self._model_instance

    # =========================
    # UNLOAD MODEL
    # =========================
    def _unload_model(self):
        try:
            if self._model_instance is not None:
                del self._model_instance
                self._model_instance = None

                gc.collect()

                if torch.cuda.is_available():
                    torch.cuda.empty_cache()

                logger.info("🧹 Model unloaded")
        except Exception as e:
            logger.warning(f"Unload error: {e}")

    # =========================
    # DISCOVER MODELS
    # =========================
    def discover_available_models(self) -> AvailableModelsResponse:
        available_models: list[AvailableModel] = []

        try:
            if not os.path.exists(RUNS_DIR):
                return AvailableModelsResponse(models=[])

            for model_dir in os.listdir(RUNS_DIR):
                full_path = os.path.join(RUNS_DIR, model_dir)

                if os.path.isdir(full_path):
                    available_models.append(
                        AvailableModel(
                            name=model_dir,
                            engine="gliner",
                            path=full_path,
                            type="gliner"
                        )
                    )

        except Exception as e:
            logger.error(f"Model discovery error: {e}")

        return AvailableModelsResponse(models=available_models)

    # =========================
    # INFO
    # =========================
    def get_model_info(self) -> ModelInfo:
        return ModelInfo(
            engine=self._current_engine or "none",
            model_path=self._current_model_path or "none",
            adapter_model=None,
            prompt_path=None,
            use_gpu=False,
            device=self._current_device,
            loaded=self._model_instance is not None,
            status="loaded" if self._model_instance else "unloaded"
        )

    def is_model_loaded(self) -> bool:
        return self._model_instance is not None

    def is_loading(self) -> bool:
        return self._is_loading

        # =========================
        # SWITCH MODEL
        # =========================
    
    def switch_model(self, engine: str, model: str, adapter_model: Optional[str] = None, prompt_path: Optional[str] = None, use_gpu: bool = False,) -> None:
        with self._switch_lock:
            logger.info(f"Switching model -> engine={engine}, model={model}")

            # unload existing model
            self._unload_model()

            # store metadata
            self._current_engine = engine
            self._current_model_path = model
            self._current_adapter_model = adapter_model
            self._current_prompt_path = prompt_path
            self._use_gpu = use_gpu

            # load model
            self._model_instance = build_engine(engine=engine, model=model, adapter_model=adapter_model, prompt_path=prompt_path, use_gpu=use_gpu)

            self._current_device = self._get_model_device(self._model_instance)

                # persist state
            self._write_state()

            logger.info("Model switched successfully")
            return ModelInfo(
                engine=self._current_engine,
                model_path=self._current_model_path,
                adapter_model=self._current_adapter_model,
                prompt_path=self._current_prompt_path,
                use_gpu=self._use_gpu,
                device=self._current_device,
                loaded=True,
                status="loaded"
            )



# =========================
# SINGLETON
# =========================
_model_manager: Optional[ModelManager] = None


def get_model_manager() -> ModelManager:
    global _model_manager
    if _model_manager is None:
        _model_manager = ModelManager()
    return _model_manager"""


