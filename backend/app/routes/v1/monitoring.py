from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.core.database import get_session
from app.models_db import (
    Record,
    SourceTerm,
    TrainingRun,
    TrainingMetric,
    TrainingEvaluation,
)
from app.schemas import GLiNERTrainingRequest
from app.services.bioner_client import start_training
from sqlmodel import Session, select, func

router = APIRouter()


@router.post("/start")
async def start_training_route(
    request: GLiNERTrainingRequest,
    db: Session = Depends(get_session),
):
    run = TrainingRun(
        dataset_id=request.dataset_id,
        status="pending",
        base_model=request.base_model,
        labels=request.labels,
    )

    db.add(run)
    db.commit()
    db.refresh(run)

    payload = {
        "run_id": run.id,
        "base_model": request.base_model,
        "training_data": request.training_data,
        "num_epochs": request.num_epochs,
        "learning_rate": request.learning_rate,
        "train_batch_size": request.train_batch_size,
        "device": request.device,
        "callback_url": "http://backend:8000/api/v1/internal/training-events",
    }

    start_training(payload)

    return {
        "run_id": run.id,
        "status": "started",
    }


@router.get("/datasets/{dataset_id}/runs")
def get_runs(
    dataset_id: int,
    db: Session = Depends(get_session),
):
    runs = db.exec(
        select(TrainingRun)
        .where(TrainingRun.dataset_id == dataset_id)
    ).all()

    return runs



@router.get("/datasets/{dataset_id}/runs")
def get_runs(
    dataset_id: int,
    db: Session = Depends(get_session),
):
    runs = db.exec(
        select(TrainingRun)
        .where(TrainingRun.dataset_id == dataset_id)
    ).all()

    return runs


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