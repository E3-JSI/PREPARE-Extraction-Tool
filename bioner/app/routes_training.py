from fastapi import APIRouter, HTTPException, status
from huggingface_hub import model_info
from pydantic import BaseModel

from app.training.job_manager import StartResult, get_training_job_manager

router = APIRouter(tags=["Training"])


class TrainingStartRequest(BaseModel):
    """Request payload to start a GLiNER fine-tuning run.

    Attributes:
        run_id (int): Backend-assigned training run identifier.
        base_model (str): HuggingFace GLiNER model path to fine-tune.
        training_data (list[dict]): Training samples, each
            ``{"tokenized_text": [...], "ner": [[start_tok, end_tok, label], ...]}``.
        eval_data (list[dict]): Optional evaluation samples in the same format.
            When non-empty, these are used for evaluation instead of a held-out
            split of the training data.
        num_epochs (int): Number of training epochs.
        learning_rate (float): Optimizer learning rate.
        train_batch_size (int): Training batch size.
        device (str): Device to train on (e.g. ``"cpu"`` or ``"cuda"``).
        val_ratio (float): Fraction of data held out for validation (ignored when
            ``eval_data`` is provided).
    """

    run_id: int
    base_model: str
    training_data: list[dict]
    eval_data: list[dict] = []
    num_epochs: int = 4
    learning_rate: float = 5e-6
    train_batch_size: int = 8
    device: str = "cpu"
    val_ratio: float = 0.2


# ==============================
# MODEL VALIDATION
# ==============================
def validate_model(model: str) -> bool:
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
    result = manager.start_job(
        run_id=request.run_id,
        base_model_path=request.base_model,
        training_data=request.training_data,
        eval_data=request.eval_data,
        device=request.device,
        num_epochs=request.num_epochs,
        learning_rate=request.learning_rate,
        train_batch_size=request.train_batch_size,
        val_ratio=request.val_ratio,
    )

    # 3. If busy -> 409 with a machine-readable reason so the frontend can show
    #    the right message: a genuinely active run vs a previous run still
    #    winding down after a stop (retry shortly).
    if result is StartResult.STOPPING:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "TRAINING_STOPPING",
                "message": "Previous training run is still stopping",
                "suggestion": "Retry in a moment"
            }
        )

    if result is not StartResult.STARTED:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "TRAINING_BUSY",
                "message": "Another training job is already running",
                "suggestion": "Wait for current training to finish"
            }
        )

    # 4. Success response
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
