"""User-triggered live evaluation of a trained model over a held-out set.

Clones the ExtractionJob async-job house pattern (start / active / status /
cancel + a background worker). A live-eval run picks a trained model and any
dataset, runs the model over that dataset's reviewed records whose gold
``SourceTerm`` annotations were NOT used to train the model (held-out), writes
the model's predictions to ``SourceTermEx`` (never ``SourceTerm``), scores them
against gold with :mod:`app.library.ner_metrics`, and stores the metrics on the
``LiveEvalJob`` row (never the shared ``Evaluation`` table).

Running a live eval hot-swaps bioner's globally-active NER model to the eval
model, so it is blocked (409) while any extraction or other live-eval job is
active, and the previously-active model is restored in a ``finally`` block.
"""

import requests
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    status,
)
from sqlmodel import Session, select

from app.core.database import Dataset, User, engine, get_session
from app.core.settings import settings
from app.interfaces import Entity
from app.library.ner_metrics import NERMetrics
from app.models_db import (
    LiveEvalJob,
    Model,
    ModelTrainRecordLink,
    Record,
    SourceTerm,
    SourceTermEx,
)
from app.routes.v1.auth import get_current_user
from app.schemas import (
    LiveEvalJobStartResponse,
    LiveEvalJobStatusResponse,
    LiveEvalStartRequest,
    MessageOutput,
)
import app.services.extraction_lock as extraction_lock
from app.services import bioner_client, training_service

router = APIRouter(tags=["BioNER"])

MATCH_TYPES = ["exact", "relaxed", "overlap"]

NO_HELDOUT_MESSAGE = (
    "No held-out reviewed records with gold annotations for this model on this "
    "dataset. Live eval scores records the model was NOT trained on."
)


# ================================================
# Held-out set + metrics helpers
# ================================================


def _heldout_record_ids(session: Session, model_id: int, dataset_id: int) -> List[int]:
    """Reviewed records in the dataset NOT used to train the model that still
    carry gold SourceTerm(s) with non-null start/end offsets."""
    trained_ids = select(ModelTrainRecordLink.record_id).where(
        ModelTrainRecordLink.model_id == model_id
    )
    records = session.exec(
        select(Record).where(
            Record.dataset_id == dataset_id,
            Record.reviewed == True,  # noqa: E712
            Record.id.not_in(trained_ids),
        )
    ).all()

    heldout: List[int] = []
    for record in records:
        has_gold = session.exec(
            select(SourceTerm.id)
            .where(SourceTerm.record_id == record.id)
            .where(SourceTerm.start_position.is_not(None))
            .where(SourceTerm.end_position.is_not(None))
        ).first()
        if has_gold:
            heldout.append(record.id)
    return heldout


def _gold_entity(term: SourceTerm) -> Entity:
    return Entity(
        text=term.value,
        label=term.label,
        start=term.start_position,
        end=term.end_position,
        score=term.score,
    )


def _pred_entity(raw: dict) -> Entity:
    return Entity(
        text=raw["text"],
        label=raw["label"],
        start=raw["start"],
        end=raw["end"],
        score=raw.get("score"),
    )


def _compute_metrics(
    gold_by_record: List[List[Entity]],
    pred_by_record: List[List[Entity]],
    dataset_labels: List[str],
) -> dict:
    """Per-label exact/relaxed/overlap P/R/F1 plus a macro aggregate over labels.

    The label set is the dataset's labels that actually appear in gold/pred
    (falling back to every label present) so absent labels don't drag the macro
    aggregate to zero. The headline number is the exact-match aggregate F1.
    """
    engine_metrics = NERMetrics(MATCH_TYPES)

    present = {
        ent.label
        for records in (gold_by_record, pred_by_record)
        for ents in records
        for ent in ents
    }
    label_set = [label for label in dataset_labels if label in present]
    if not label_set:
        label_set = sorted(present)

    per_label: dict = {}
    for label in label_set:
        per_label[label] = {}
        for match_type in MATCH_TYPES:
            precision, recall, f1 = engine_metrics.evaluate_ner_performance(
                gold_by_record, pred_by_record, match_type=match_type, label=label
            )
            per_label[label][match_type] = {
                "precision": precision,
                "recall": recall,
                "f1": f1,
            }

    aggregate: dict = {}
    for match_type in MATCH_TYPES:
        if label_set:
            scores = [per_label[label][match_type] for label in label_set]
            aggregate[match_type] = {
                "precision": sum(s["precision"] for s in scores) / len(scores),
                "recall": sum(s["recall"] for s in scores) / len(scores),
                "f1": sum(s["f1"] for s in scores) / len(scores),
            }
        else:
            aggregate[match_type] = {"precision": 0.0, "recall": 0.0, "f1": 0.0}

    return {
        "labels": label_set,
        "match_types": MATCH_TYPES,
        "per_label": per_label,
        "aggregate": aggregate,
        "aggregate_method": "macro",
        "gold_entity_count": sum(len(e) for e in gold_by_record),
        "pred_entity_count": sum(len(e) for e in pred_by_record),
        "heldout_count": len(gold_by_record),
    }


# ================================================
# Routes
# ================================================


def _ensure_model_artifact(model: Model) -> None:
    """Fail fast when the model's on-disk artifact no longer exists.

    A ``Model`` row can outlive its folder (e.g. the folder was deleted but an
    ExtractionJob reference keeps the row alive through rescans); activating it
    would fail deep in the background worker. Only paths under bioner's scanned
    models dir are checked — anything else (HF ids) is validated at activation.
    """
    try:
        scan = bioner_client.get_available_models()
    except requests.RequestException:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Extraction service unavailable",
        )
    models_dir = (scan.get("models_dir") or "").rstrip("/")
    path = model.path.rstrip("/")
    if not models_dir or not path.startswith(models_dir + "/"):
        return
    scanned = {m["path"].rstrip("/") for m in scan.get("models") or []}
    if path not in scanned:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Model artifact no longer exists on disk: {model.path}. "
                "Rescan models and pick an existing model."
            ),
        )


def _owned_dataset(db: Session, dataset_id: int, current_user: User) -> Dataset:
    dataset = db.get(Dataset, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
        )
    if dataset.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this dataset",
        )
    return dataset


@router.post("/live-eval/start", response_model=LiveEvalJobStartResponse)
def start_live_eval(
    payload: LiveEvalStartRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """Kick off a live evaluation of ``model_id`` over ``dataset_id``'s held-out
    reviewed records. Returns immediately with a job id to poll."""
    dataset = _owned_dataset(db, payload.dataset_id, current_user)

    model = db.get(Model, payload.model_id)
    if model is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Model not found")
    if not model.path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Model has no trained artifact to evaluate",
        )
    _ensure_model_artifact(model)

    # Live eval hot-swaps the global NER model; refuse while any extraction or
    # live-eval job is running instance-wide (they share bioner's single model).
    if extraction_lock.any_ner_job_active(db):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An extraction or live-eval job is already running",
        )

    heldout = _heldout_record_ids(db, payload.model_id, payload.dataset_id)
    total = len(heldout)

    # Only one currently_used=True at a time, matching ExtractionJob/ClusterJob.
    currently_used_job = db.exec(
        select(LiveEvalJob)
        .where(LiveEvalJob.currently_used == True)  # noqa: E712
        .order_by(LiveEvalJob.created_at.desc())
    ).first()
    if currently_used_job is not None:
        currently_used_job.currently_used = False
        db.add(currently_used_job)
        db.commit()

    job = LiveEvalJob(
        dataset_id=payload.dataset_id,
        model_id=payload.model_id,
        total=total,
        completed=0,
        status="pending",
        currently_used=True,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    if total == 0:
        job.status = "completed"
        job.metrics = {
            "message": NO_HELDOUT_MESSAGE,
            "heldout_count": 0,
            "labels": [],
            "match_types": MATCH_TYPES,
            "per_label": {},
            "aggregate": {},
            "aggregate_method": "macro",
        }
        job.updated_at = datetime.now(timezone.utc)
        db.add(job)
        db.commit()
        return LiveEvalJobStartResponse(
            job_id=job.id,
            dataset_id=job.dataset_id,
            model_id=job.model_id,
            total=job.total,
            status=job.status,
            message=NO_HELDOUT_MESSAGE,
        )

    background_tasks.add_task(
        run_live_eval_job,
        job_id=job.id,
        model_id=payload.model_id,
        dataset_id=payload.dataset_id,
        labels=list(dataset.labels or []),
    )

    return LiveEvalJobStartResponse(
        job_id=job.id,
        dataset_id=job.dataset_id,
        model_id=job.model_id,
        total=total,
        status=job.status,
    )


@router.get("/live-eval/active", response_model=Optional[LiveEvalJobStatusResponse])
def get_active_live_eval(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """Return the latest pending/running live-eval job the caller owns, or null."""
    jobs = db.exec(
        select(LiveEvalJob)
        .where((LiveEvalJob.status == "pending") | (LiveEvalJob.status == "running"))
        .order_by(LiveEvalJob.created_at.desc())
    ).all()
    for job in jobs:
        dataset = db.get(Dataset, job.dataset_id)
        if dataset is not None and dataset.user_id == current_user.id:
            return _status_response(job)
    return None


@router.get("/live-eval/{job_id}/status", response_model=LiveEvalJobStatusResponse)
def get_live_eval_status(
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """Return progress (and, once done, metrics) for a live-eval job."""
    job = db.get(LiveEvalJob, job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Live-eval job not found"
        )
    _owned_dataset(db, job.dataset_id, current_user)
    return _status_response(job)


@router.post("/live-eval/{job_id}/cancel", response_model=MessageOutput)
def cancel_live_eval(
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """Request cancellation of a live-eval job. Already-scored records remain."""
    job = db.get(LiveEvalJob, job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Live-eval job not found"
        )
    _owned_dataset(db, job.dataset_id, current_user)

    if job.status in {"completed", "failed", "cancelled"}:
        return MessageOutput(message=f"Job already {job.status}")

    job.status = "cancelled"
    job.updated_at = datetime.now(timezone.utc)
    db.add(job)
    db.commit()
    return MessageOutput(message="Cancellation requested")


def _status_response(job: LiveEvalJob) -> LiveEvalJobStatusResponse:
    return LiveEvalJobStatusResponse(
        job_id=job.id,
        dataset_id=job.dataset_id,
        model_id=job.model_id,
        total=job.total,
        completed=job.completed,
        status=job.status,
        error_message=job.error_message,
        metrics=job.metrics,
    )


# ================================================
# Background worker
# ================================================


def run_live_eval_job(
    job_id: int, model_id: int, dataset_id: int, labels: List[str]
) -> None:
    """Score ``model_id``'s predictions over the dataset's held-out reviewed
    records. Hot-swaps bioner to the eval model, writing predictions to
    ``SourceTermEx``, then restores the previously-active model in ``finally``."""
    with Session(engine) as session:
        job = session.get(LiveEvalJob, job_id)
        if job is None:
            return
        if job.status == "cancelled":
            return

        model = session.get(Model, model_id)
        if model is None or not model.path:
            job.status = "failed"
            job.error_message = "Model has no trained artifact to evaluate"
            job.updated_at = datetime.now(timezone.utc)
            session.add(job)
            session.commit()
            return

        job.status = "running"
        job.updated_at = datetime.now(timezone.utc)
        session.add(job)
        session.commit()

        record_ids = _heldout_record_ids(session, model_id, dataset_id)
        job.total = len(record_ids)
        job.updated_at = datetime.now(timezone.utc)
        session.add(job)
        session.commit()

        # Capture the currently-active model BEFORE hot-swapping so it can be
        # restored afterward (the DB holds the source of truth for what bioner
        # currently serves — set at model-selection time).
        prev_model = training_service.get_global_active_model(session)
        prev_path = prev_model.path if prev_model is not None else None

        try:
            bioner_client.activate_model(model.path)

            # Clear this model's prior predictions for these records so a re-run
            # scores fresh output rather than accumulating duplicates.
            stale = session.exec(
                select(SourceTermEx)
                .where(SourceTermEx.model_id == model_id)
                .where(SourceTermEx.record_id.in_(record_ids))
            ).all()
            for term in stale:
                session.delete(term)
            if stale:
                session.commit()

            gold_by_record: List[List[Entity]] = []
            pred_by_record: List[List[Entity]] = []

            for record_id in record_ids:
                session.refresh(job)
                if job.status == "cancelled":
                    job.updated_at = datetime.now(timezone.utc)
                    session.add(job)
                    session.commit()
                    return

                record = session.get(Record, record_id)
                if record is None:
                    job.completed += 1
                    session.add(job)
                    session.commit()
                    continue

                request_data = {"medical_text": record.text, "labels": labels}
                response = requests.post(
                    f"{settings.EXTRACT_HOST}/ner", json=request_data, timeout=300
                )
                response.raise_for_status()
                entities = response.json()

                session.add_all(
                    SourceTermEx(
                        record_id=record_id,
                        model_id=model_id,
                        value=e["text"],
                        label=e["label"],
                        start_position=e["start"],
                        end_position=e["end"],
                        score=e.get("score"),
                    )
                    for e in entities
                )

                gold_terms = session.exec(
                    select(SourceTerm)
                    .where(SourceTerm.record_id == record_id)
                    .where(SourceTerm.start_position.is_not(None))
                    .where(SourceTerm.end_position.is_not(None))
                ).all()

                gold_by_record.append([_gold_entity(t) for t in gold_terms])
                pred_by_record.append([_pred_entity(e) for e in entities])

                job.completed += 1
                job.updated_at = datetime.now(timezone.utc)
                session.add(job)
                session.commit()

            metrics = _compute_metrics(gold_by_record, pred_by_record, labels)
            job.metrics = metrics
            job.status = "completed"
            job.updated_at = datetime.now(timezone.utc)
            session.add(job)
            session.commit()
        except Exception as exc:
            # Catch everything: an escaped exception would leave the job stuck
            # in "running" forever (the frontend polls it as a zombie).
            session.rollback()
            job = session.get(LiveEvalJob, job_id)
            if job is not None:
                job.status = "failed"
                job.error_message = (
                    bioner_client.http_error_detail(exc)
                    or str(exc)
                    or exc.__class__.__name__
                )
                job.updated_at = datetime.now(timezone.utc)
                session.add(job)
                session.commit()
        finally:
            # Restore the previously-active model even on failure/cancel.
            try:
                bioner_client.activate_model(prev_path)
            except Exception:
                pass
