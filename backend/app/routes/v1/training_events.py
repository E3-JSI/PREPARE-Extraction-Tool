import logging
logger = logging.getLogger(__name__)


from fastapi import APIRouter, Depends
from sqlmodel import Session, delete, select

from app.core.database import get_session
from app.models_db import ModelArtifact, TrainingEvaluation, TrainingRun, TrainingMetric
from app.services.websocket_manager import manager

router = APIRouter()


def safe_float(x):
    try:
        return float(x) if x is not None else None
    except (TypeError, ValueError):
        return None

@router.post("/internal/training-events")
async def receive_training_event(
    payload: dict,
    db: Session = Depends(get_session),
):
    logger.info(f"[EVENT RECEIVED] {payload}")

    event_type = payload.get("type")
    run_id = payload.get("run_id")

    if not run_id:
        return {"ok": False, "error": "missing run_id"}

    run = db.get(TrainingRun, run_id)

    # --------------------------
    # TRAINING INFO
    # --------------------------
    if event_type == "training_info":
        if run:
            run.status = "running"
            db.commit()

    # --------------------------
    # METRICS (FIXED)
    # --------------------------
    elif event_type == "epoch_update":
        epoch_raw = payload.get("epoch")    
        epoch = float(epoch_raw) if epoch_raw is not None else None

        loss = safe_float(payload.get("loss"))
        precision = safe_float(payload.get("precision"))
        recall = safe_float(payload.get("recall"))
        f1 = safe_float(payload.get("f1"))

        # 🚨 IMPORTANT: don't insert empty metric rows
        # (this is what was breaking your DB)
        if loss is None and precision is None and recall is None and f1 is None:
            logger.info("[SKIP METRIC] empty epoch_update payload")
            await manager.broadcast(payload)
            return {"ok": True, "skipped": True}

        # Optional: enforce DB NOT NULL safety
        if loss is None:
            logger.warning("[FIXING METRIC] missing loss -> default 0.0")
            loss = 0.0

        metric = TrainingMetric(
            run_id=run_id,
            epoch=safe_float(epoch_raw) or 0.0,
            loss=loss,
            precision=precision,
            recall=recall,
            f1=f1,
        )

        db.commit()
        try:
            db.add(metric)
            db.commit()
        except Exception as e:
            db.rollback()
            logger.error(e)
            raise

    # --------------------------
    # MODEL SAVED
    # --------------------------
    elif event_type == "model_saved":
        model_path = payload.get("output_path")

        if model_path and run:
            existing = db.query(ModelArtifact).filter(
                ModelArtifact.run_id == run_id,
                ModelArtifact.model_path == model_path,
            ).first()

            if not existing:
                evaluation = db.query(TrainingEvaluation).filter(
                    TrainingEvaluation.run_id == run_id
                ).first()

                db.add(ModelArtifact(
                    run_id=run_id,
                    dataset_id=run.dataset_id if run else None,
                    model_path=model_path,
                    f1_score=evaluation.f1 if evaluation else 0.0,
                    precision=evaluation.precision if evaluation else 0.0,
                    recall=evaluation.recall if evaluation else 0.0,
                    engine=payload.get("engine", "gliner"),
                ))
                db.commit()

    # --------------------------
    # EVALUATION
    # --------------------------
    elif event_type == "evaluation_completed":
        metrics = payload.get("metrics") or {}

        f1 = safe_float(metrics.get("f1_score")) or 0.0
        precision = safe_float(metrics.get("precision")) or 0.0
        recall = safe_float(metrics.get("recall")) or 0.0
        per_label = metrics.get("per_label") or {}

        db.execute(
            delete(TrainingEvaluation).where(
                TrainingEvaluation.run_id == run_id
            )
        )

        db.add(TrainingEvaluation(
            run_id=run_id,
            precision=precision,
            recall=recall,
            f1=f1,
            per_label=per_label,
        ))

        db.commit()

    # --------------------------
    # COMPLETED
    # --------------------------
    elif event_type == "completed":
        if run:
            run.status = "completed"
            run.output_model_path = payload.get("output_path")
            db.commit()

    # --------------------------
    # FAILED
    # --------------------------
    elif event_type == "error":
        if run:
            run.status = "failed"
            db.commit()

    # broadcast to frontend (real-time progress)
    try:
        await manager.broadcast(payload)
    except Exception as e:
        logger.warning(f"broadcast failed: {e}")

    return {"ok": True}