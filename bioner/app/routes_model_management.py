from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from fastapi.params import Depends

from pathlib import Path
from pytz import timezone
from sqlmodel import Session

from app.model_manager import get_model_manager
from app.interfaces import (
    ModelInfo,
    ModelHealthCheck,
    ModelSwitchRequest,
    AvailableModelsResponse,
)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR   = PROJECT_ROOT / "models" / "gliner"

router = APIRouter(tags=["Model Management"])

# -------------------------
# LOAD MODEL FROM BACKEND (LOGIN)
# -------------------------
@router.post("/models/load-user")
def load_user_model(payload: dict):
    model_path = payload.get("model_path")

    manager = get_model_manager()
    manager.load_user_model(model_path)

    return {"status": "ok"}



# -------------------------
# MANUAL SWITCH (ADMIN / UI)
# -------------------------
@router.post("/models/switch")
def switch_model(request: dict):
    manager = get_model_manager()

    return manager.switch_model(
        engine=request["engine"],
        model=request["model"],
        adapter_model=request.get("adapter_model"),
        prompt_path=request.get("prompt_path"),
        use_gpu=request.get("use_gpu", False),
    )


# -------------------------
# CURRENT MODEL
# -------------------------
@router.get("/models/current")
def get_current_model():
    manager = get_model_manager()
    return manager.get_model_info()

@router.post("/models/switch2", response_model=ModelInfo, status_code=status.HTTP_200_OK)
async def switch_model(request: ModelSwitchRequest) -> ModelInfo:
    try:
        manager    = get_model_manager()
        model_info = manager.switch_model(
            engine=request.engine,
            model=request.model,
            adapter_model=request.adapter_model,
            prompt_path=request.prompt_path,
            use_gpu=request.use_gpu
        )
        return model_info
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Unexpected error while switching model: {str(e)}")


@router.get("/models/current2", response_model=ModelInfo)
async def get_current_model() -> ModelInfo:
    manager = get_model_manager()
    return manager.get_model_info()


@router.get("/models/current3")
async def get_current_model():
    manager = get_model_manager()
    return manager.get_model_info()


@router.get("/models/health", response_model=ModelHealthCheck)
async def model_health_check() -> ModelHealthCheck:
    manager = get_model_manager()
    return manager.health_check()


@router.get("/models/available", response_model=AvailableModelsResponse)
async def list_available_models() -> AvailableModelsResponse:
    manager = get_model_manager()
    return manager.discover_available_models()
