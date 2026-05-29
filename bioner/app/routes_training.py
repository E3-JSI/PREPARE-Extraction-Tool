from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from huggingface_hub import model_info
from fastapi import HTTPException

from app.training.job_manager import get_training_job_manager

router = APIRouter(tags=["Training"])


class TrainingStartRequest(BaseModel):
    run_id: int
    base_model: str
    training_data: list[dict]
    num_epochs: int = 4
    learning_rate: float = 5e-6
    train_batch_size: int = 8
    device: str = "cpu"

# ==============================
# MODEL VALIDATION
# ==============================
def validate_model(model: str):
    try:
        model_info(model)
        return True
    except Exception:
        return False


@router.post("/training/start", status_code=status.HTTP_202_ACCEPTED)
async def start_training(request: TrainingStartRequest):

    # 1. Validate model
    if not validate_model(request.base_model):
        raise HTTPException(
            status_code=400,
            detail={
                "error": "INVALID_MODEL",
                "message": f"Model not found: {request.base_model}",
                "suggestion": "Please select a valid HuggingFace GLiNER model"
            }
        )

    # 2. Start job
    manager = get_training_job_manager()
    started = manager.start_job(
        run_id=request.run_id,
        base_model_path=request.base_model,
        training_data=request.training_data,
        device=request.device,
        num_epochs=request.num_epochs,
        learning_rate=request.learning_rate,
        train_batch_size=request.train_batch_size,
    )

    # 3. If busy → error
    if not started:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "TRAINING_BUSY",
                "message": "Another training job is already running",
                "suggestion": "Wait for current training to finish"
            }
        )

    # 4. Success response (NORMAL RETURN, NOT EXCEPTION)
    return {
        "run_id": request.run_id,
        "status": "accepted"
    }

@router.get("/training/status/{run_id}")
async def get_training_status(run_id: int):
    manager = get_training_job_manager()
    snapshot = manager.get_status(run_id)
    if snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Training run {run_id} not found",
        )
    return snapshot

@router.post("/training/stop/{run_id}")
async def stop_training(run_id: int):
    manager = get_training_job_manager()
    stopped = manager.stop_job(run_id)
    if not stopped:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No active training run with id {run_id}",
        )
    return {"message": "Stop requested"}
