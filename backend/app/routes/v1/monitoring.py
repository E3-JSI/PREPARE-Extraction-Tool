import asyncio
import logging
import os
import time
import threading
from typing import List

import requests
from jose import jwt, JWTError
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlmodel import Session, select, func

from app.core.database import engine, get_session
from app.core.settings import settings
from app.models_db import (
    Dataset,
    Record,
    SourceTerm,
    TrainingRun,
    TrainingMetric,
    TrainingEvaluation,
)
from app.routes.v1.auth import get_current_user
from app.models_db import User
from app.schemas import GLiNERTrainingRequest
from app.services.gliner_data_service import build_gliner_training_data, load_reviewed_training_data

# =========================
# Setup
# =========================
router = APIRouter()

os.makedirs("logs", exist_ok=True)
logger = logging.getLogger(__name__)
if not logger.handlers:
    fh = logging.FileHandler(os.path.join("logs", "monitoring.log"))
    ch = logging.StreamHandler()
    fmt = logging.Formatter("%(asctime)s - %(levelname)s - %(name)s - %(message)s")
    fh.setFormatter(fmt); ch.setFormatter(fmt)
    logger.addHandler(fh); logger.addHandler(ch)
logger.setLevel(logging.INFO)

# =========================
# Global state
# =========================
active_connections: List[WebSocket] = []
training_state = {"stop_requested": False}
main_loop = None


# =========================
# Broadcast helper
# =========================
async def broadcast_metric(data: dict):
    dead = []
    for ws in active_connections:
        try:
            await ws.send_json(data)
        except Exception:
            dead.append(ws)
    for ws in dead:
        if ws in active_connections:
            active_connections.remove(ws)


def emit_training_update(payload: dict):
    global main_loop
    if not main_loop:
        return
    asyncio.run_coroutine_threadsafe(broadcast_metric(payload), main_loop)


# =========================
# WebSocket endpoint
# =========================
@router.websocket("/ws/training")
async def training_ws(websocket: WebSocket):
    global main_loop
    main_loop = asyncio.get_running_loop()

    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=1008)
        return

    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        if not payload.get("sub"):
            await websocket.close(code=1008)
            return
    except JWTError:
        await websocket.close(code=1008)
        return

    await websocket.accept()
    active_connections.append(websocket)
    logger.info(f"WebSocket connected: {payload.get('sub')}")

    try:
        while True:
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        if websocket in active_connections:
            active_connections.remove(websocket)


# =========================
# Background training job
# =========================
def run_gliner_training_job(
    run_id: int,
    training_examples: list[dict],
    request: GLiNERTrainingRequest,
) -> None:
    """Polls bioner for training progress and mirrors updates to DB + WebSocket."""
    with Session(engine) as db:
        run = db.get(TrainingRun, run_id)
        if run:
            run.status = "running"
            db.add(run)
            db.commit()

    emit_training_update({"type": "training_start", "run_id": run_id})

    try:
        response = requests.post(
            f"{settings.EXTRACT_HOST}/training/start",
            json={
                "run_id": run_id,
                "base_model": request.base_model,
                "training_data": training_examples,
                "num_epochs": request.num_epochs,
                "learning_rate": request.learning_rate,
                "train_batch_size": request.train_batch_size,
                "val_ratio": request.val_ratio,
                "device": request.device,
            },
            timeout=30,
        )
        response.raise_for_status()
    except Exception as e:
        logger.error(f"Failed to start training on bioner: {e}")
        _mark_run(run_id, "failed")
        emit_training_update({"type": "error", "run_id": run_id, "message": str(e)})
        return

    # Poll bioner until training completes
    while True:
        if training_state.get("stop_requested"):
            training_state["stop_requested"] = False
            try:
                requests.post(f"{settings.EXTRACT_HOST}/training/stop/{run_id}", timeout=10)
            except Exception:
                pass
            _mark_run(run_id, "stopped")
            emit_training_update({"type": "stopped", "run_id": run_id})
            return

        try:
            status_resp = requests.get(
                f"{settings.EXTRACT_HOST}/training/status/{run_id}",
                timeout=10,
            )
            status_resp.raise_for_status()
            status_data = status_resp.json()
        except Exception as e:
            logger.warning(f"Failed to poll training status: {e}")
            time.sleep(5)
            continue

        for event in status_data.get("new_events", []):
            emit_training_update(event)
            _persist_metric_if_epoch(run_id, event)

        job_status = status_data.get("status")
        if job_status in ("completed", "failed", "stopped"):
            break

        time.sleep(5)

    if job_status == "completed":
        output_path = status_data.get("output_path")
        _mark_run(run_id, "completed", output_model_path=output_path)
        emit_training_update({
            "type": "completed",
            "run_id": run_id,
            "output_path": output_path,
        })
    else:
        _mark_run(run_id, job_status or "failed")
        error_msg = status_data.get("error") or ""
        emit_training_update({"type": "error", "run_id": run_id, "message": error_msg})


def _mark_run(run_id: int, status: str, output_model_path: str = None) -> None:
    with Session(engine) as db:
        run = db.get(TrainingRun, run_id)
        if run:
            run.status = status
            if output_model_path:
                run.output_model_path = output_model_path
            db.add(run)
            db.commit()


def _persist_metric_if_epoch(run_id: int, event: dict) -> None:
    if event.get("type") != "epoch_update":
        return
    with Session(engine) as db:
        epoch = event.get("epoch", 0)
        db.add(TrainingMetric(
            run_id=run_id,
            epoch=int(epoch),
            loss=float(event.get("loss", 0) or event.get("train_loss", 0)),
            precision=0.0,
            recall=0.0,
            f1=float(event.get("eval_f1", 0)),
        ))
        db.commit()


# =========================
# Training endpoints
# =========================
@router.post("/start")
async def start_training(
    request: GLiNERTrainingRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    # Reject if a run is already active for this dataset
    existing = db.exec(
        select(TrainingRun)
        .where(TrainingRun.dataset_id == request.dataset_id)
        .where(TrainingRun.status == "running")
    ).first()
    if existing:
        raise HTTPException(409, "Training already in progress for this dataset")

    records, source_terms = load_reviewed_training_data(db, request.dataset_id, request.labels)
    training_examples = build_gliner_training_data(records, source_terms)

    if len(training_examples) < 2:
        raise HTTPException(
            422,
            f"Not enough reviewed training examples ({len(training_examples)} found). "
            "Ensure source terms are clustered and clusters are reviewed.",
        )

    run = TrainingRun(
        dataset_id=request.dataset_id,
        status="pending",
        base_model=request.base_model,
        labels=request.labels,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    training_state["stop_requested"] = False
    background_tasks.add_task(run_gliner_training_job, run.id, training_examples, request)
    return {"run_id": run.id, "status": "pending"}


@router.post("/stop")
async def stop_training():
    training_state["stop_requested"] = True
    return {"message": "Stop requested"}


@router.get("/runs/{run_id}")
def get_run_status(run_id: int, db: Session = Depends(get_session)):
    run = db.get(TrainingRun, run_id)
    if not run:
        raise HTTPException(404, "Training run not found")
    return {
        "run_id": run.id,
        "dataset_id": run.dataset_id,
        "status": run.status,
        "base_model": run.base_model,
        "labels": run.labels,
        "output_model_path": run.output_model_path,
        "created_at": run.created_at,
    }


# =========================
# Monitoring GET endpoints (kept as-is)
# =========================
@router.get("/datasets/{dataset_id}/full-stats")
def get_full_stats(dataset_id: int, db: Session = Depends(get_session)):
    total_records = db.exec(
        select(func.count(Record.id)).where(Record.dataset_id == dataset_id)
    ).one()

    total_terms = db.exec(
        select(func.count(SourceTerm.id))
        .join(Record, Record.id == SourceTerm.record_id)
        .where(Record.dataset_id == dataset_id)
    ).one()

    label_distribution = db.exec(
        select(SourceTerm.label, func.count(SourceTerm.id))
        .join(Record, Record.id == SourceTerm.record_id)
        .where(Record.dataset_id == dataset_id)
        .group_by(SourceTerm.label)
    ).all()

    return {
        "totalRecords": total_records,
        "totalTerms": total_terms,
        "labelDistribution": {label: count for label, count in label_distribution},
    }


@router.get("/evaluations")
def get_all_evaluations(db: Session = Depends(get_session)):
    rows = db.exec(
        select(TrainingEvaluation, TrainingRun)
        .join(TrainingRun, TrainingRun.id == TrainingEvaluation.run_id)
    ).all()
    return [
        {
            "run_id": ev.run_id,
            "dataset_id": run.dataset_id,
            "precision": ev.precision,
            "recall": ev.recall,
            "f1": ev.f1,
            "per_label": ev.per_label,
        }
        for ev, run in rows
    ]


@router.get("/runs/{run_id}/evaluation")
def get_evaluation(run_id: int, db: Session = Depends(get_session)):
    evaluation = db.exec(
        select(TrainingEvaluation).where(TrainingEvaluation.run_id == run_id)
    ).first()
    if not evaluation:
        return {"run_id": run_id, "precision": 0, "recall": 0, "f1": 0, "per_label": {}}
    return {
        "run_id": evaluation.run_id,
        "precision": evaluation.precision,
        "recall": evaluation.recall,
        "f1": evaluation.f1,
        "per_label": evaluation.per_label,
    }


@router.get("/datasets/{dataset_id}/runs")
def get_runs_for_dataset(dataset_id: int, db: Session = Depends(get_session)):
    runs = db.exec(
        select(TrainingRun)
        .where(TrainingRun.dataset_id == dataset_id)
        .order_by(TrainingRun.id.desc())
    ).all()
    return [{"run_id": run.id, "dataset_id": run.dataset_id, "status": run.status} for run in runs]


@router.get("/datasets/{dataset_id}/runs/evaluations")
def get_dataset_runs_evaluations(dataset_id: int, db: Session = Depends(get_session)):
    runs = db.exec(select(TrainingRun).where(TrainingRun.dataset_id == dataset_id)).all()
    result = []
    for run in runs:
        evals = db.exec(
            select(TrainingEvaluation).where(TrainingEvaluation.run_id == run.id)
        ).all()
        result.append({
            "run_id": run.id,
            "dataset_id": dataset_id,
            "evaluations": [
                {
                    "precision": e.precision or 0,
                    "recall": e.recall or 0,
                    "f1": e.f1 or 0,
                    "per_label": e.per_label or {},
                }
                for e in evals
            ],
        })
    return result
