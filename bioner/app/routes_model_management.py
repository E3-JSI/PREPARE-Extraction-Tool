from fastapi import APIRouter, HTTPException, status

from app.model_manager import get_model_manager
from app.interfaces import (
    ModelInfo,
    ModelHealthCheck,
    ModelSwitchRequest,
    AvailableModelsResponse,
)

router = APIRouter(tags=["Model Management"])


@router.post("/models/switch", response_model=ModelInfo, status_code=status.HTTP_200_OK)
async def switch_model(request: ModelSwitchRequest) -> ModelInfo:
    try:
        manager = get_model_manager()
        model_info = manager.switch_model(
            engine=request.engine,
            model=request.model,
            adapter_model=request.adapter_model,
            prompt_path=request.prompt_path,
            use_gpu=request.use_gpu
        )
        return model_info
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected error while switching model: {str(e)}"
        )


@router.get("/models/current", response_model=ModelInfo)
async def get_current_model() -> ModelInfo:
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
