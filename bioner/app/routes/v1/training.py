import os

from app.core.models.embedding_base import BaseModel
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session
import requests
 
from pydantic import BaseModel
from typing import List, Dict, Any

router = APIRouter()


from app.core.database import get_session
from app.schemas import GLiNERTrainingRequest
from app.models_db import TrainingRun
from app.services.gliner_data_service import (
    load_reviewed_training_data,
    build_gliner_training_data,
)

router = APIRouter()

BACKEND_URL = "http://prepare-backend:8000"


import requests
from typing import List
from datetime import datetime, timezone

from app.core.database import get_session
from app.core.settings import settings
from app.models_db import (TrainingRun,)

from app.routes.v1.auth import get_current_user
from app.schemas import GLiNERTrainingRequest
from app.services.gliner_data_service import (
    load_reviewed_training_data,
    build_gliner_training_data,
)

router = APIRouter()


BACKEND_URL = os.getenv("BACKEND_URL", "http://prepare-backend:8000")


class TrainRequest(BaseModel):
    run_id: int
    dataset_id: int
    labels: list[str]
    base_model: str
    training_data: list


TRAIN_JOBS = {}
STOP_FLAGS = {}


def notify_backend(payload):
    try:
        requests.post(
            f"{BACKEND_URL}/api/v1/training/event",
            json=payload,
            timeout=5,
        )
    except Exception as e:
        print("backend callback failed:", e)


class TrainRequest(BaseModel):
    run_id: int
    base_model: str
    training_data: List[Dict[str, Any]]
    num_epochs: int
    learning_rate: float
    train_batch_size: int
    device: str

@router.post("/training/start")
def start_training(request: TrainRequest):

    if not request.training_data:
        raise HTTPException(400, "No training data")

    print(f"[BIONER] Training run {request.run_id}")
    print(f"Samples: {len(request.training_data)}")

    # call trainer here
    return {
        "run_id": request.run_id,
        "status": "started",
        "samples": len(request.training_data),
    }

@router.get("/training/status/{run_id}")
def status(run_id: int):
    return TRAIN_JOBS.get(run_id, {"status": "not_found"})


@router.post("/training/stop/{run_id}")
def stop(run_id: int):
    STOP_FLAGS[run_id] = True
    return {"status": "stopping"}