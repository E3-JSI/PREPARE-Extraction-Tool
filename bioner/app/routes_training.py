from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.training.job_manager import get_training_job_manager

router = APIRouter(tags=["Training"])


class TrainingStartRequest(BaseModel):
    run_id: int
    base_model: str
    training_data: list[dict]
    num_epochs: int = 4
    learning_rate: float = 5e-6
    train_batch_size: int = 8
    val_ratio: float = 0.2
    device: str = "cpu"


@router.post("/training/start", status_code=status.HTTP_202_ACCEPTED)
async def start_training(request: TrainingStartRequest):
    manager = get_training_job_manager()
    started = manager.start_job(
        run_id=request.run_id,
        base_model_path=request.base_model,
        training_data=request.training_data,
        device=request.device,
        num_epochs=request.num_epochs,
        learning_rate=request.learning_rate,
        train_batch_size=request.train_batch_size,
        val_ratio=request.val_ratio,
    )
    if not started:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A training job is already running",
        )
    return {"run_id": request.run_id, "status": "accepted"}


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
