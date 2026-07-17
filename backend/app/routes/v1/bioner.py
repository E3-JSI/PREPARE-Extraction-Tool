import os
import requests
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from sqlmodel import Session, func, select

from app.core.database import Dataset, User, engine, get_session
from app.core.settings import settings
from app.interfaces import Entity, LabelsInput, NERRequest
from app.library.record_processing import (
    auto_link_entities_for_record,
    link_dates_for_record,
)
from app.models_db import (
    ExtractionJob,
    Model,
    Record,
    SourceTerm,
    TrainingRun,
)
from app.routes.v1.auth import get_current_user
from app.schemas import (
    ActiveModelResponse,
    ActiveTrainingRunResponse,
    DefaultModelInfo,
    DiscoveredModelSummary,
    ExtractionJobStartResponse,
    ExtractionJobStatusResponse,
    FullStatsRequest,
    FullStatsResponse,
    GLiNERTrainingRequest,
    MessageOutput,
    LabelErrorAnalysis,
    ModelDetailResponse,
    ModelSummary,
    ModelsOutput,
    RescanModelsResponse,
    RunErrorAnalysisResponse,
    RunEvaluationResponse,
    SetActiveModelRequest,
    TrainingMetricPoint,
    TrainingRunsOutput,
    TrainingRunSummary,
    TrainingRunUpdate,
    TrainingStartResponse,
    create_pagination_metadata,
)
import app.services.extraction_lock as extraction_lock
from app.services import (
    bioner_client,
    evaluation_service,
    gliner_data_service,
    training_service,
)
from app.services.websocket_manager import manager

router = APIRouter(tags=["BioNER"])


@router.post("/extract", response_model=List[Entity])
def extract_entities(
    request: NERRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Extract named entities from medical text using the BioNER service.
    """

    try:
        response = requests.post(
            f"{settings.EXTRACT_HOST}/ner", json=request.dict(), timeout=300
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Extract service unavailable",
        )


@router.post("/{dataset_id}/records/{record_id}/extract", response_model=MessageOutput)
def extract_entities_from_record(
    dataset_id: int,
    record_id: int,
    labels: LabelsInput,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    # Verify dataset ownership
    dataset = db.get(Dataset, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )
    if dataset.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this dataset",
        )

    statement = (
        select(Record)
        .where(Record.id == record_id)
        .where(Record.dataset_id == dataset_id)
    )
    record = db.exec(statement).one_or_none()
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Record not found in this dataset",
        )

    if record.reviewed:
        return MessageOutput(
            message=f"Record {record_id} is reviewed; extraction skipped"
        )

    # This route does NOT create an ExtractionJob, so it is outside the
    # extraction-active lock (which only inspects ExtractionJob rows). That is an
    # accepted limitation — single-record extraction is synchronous and
    # short-lived; the lock covers batch jobs only.
    #
    # An explicit single-record (re-)extract always re-runs the model and writes
    # SourceTerm fresh — no shortcut restoring cached terms.

    # Delete only automatically extracted SourceTerms for this record
    auto_terms = db.exec(
        select(SourceTerm)
        .where(SourceTerm.record_id == record_id)
        .where(SourceTerm.automatically_extracted == True)  # noqa: E712
    ).all()

    for term in auto_terms:
        db.delete(term)
    db.flush()

    request_data = {"medical_text": record.text, "labels": labels.labels}

    try:
        response = requests.post(
            f"{settings.EXTRACT_HOST}/ner", json=request_data, timeout=300
        )
        response.raise_for_status()
        entities = response.json()
    except requests.RequestException:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Extraction service unavailable",
        )

    # Keep manually created/edited SourceTerms and avoid duplicating them
    existing_keys = {
        (t.value, t.label, t.start_position, t.end_position)
        for t in db.exec(
            select(SourceTerm).where(SourceTerm.record_id == record_id)
        ).all()
    }

    seen_in_response = set()
    new_terms: List[SourceTerm] = []

    for entity in entities:
        key = (entity["text"], entity["label"], entity["start"], entity["end"])

        if key in seen_in_response:
            continue
        seen_in_response.add(key)

        if key in existing_keys:
            continue
        existing_keys.add(key)
        new_terms.append(
            SourceTerm(
                record_id=record_id,
                value=entity["text"],
                label=entity["label"],
                start_position=entity["start"],
                end_position=entity["end"],
                score=entity.get("score"),
                automatically_extracted=True,
            )
        )

    if new_terms:
        db.add_all(new_terms)
        db.flush()
        link_dates_for_record(db, record, dataset)
        auto_link_entities_for_record(db, record, dataset)

    db.commit()

    return MessageOutput(
        message=f"Extracted and saved {len(new_terms)} entities from record {record_id}"
    )


@router.post("/{dataset_id}/records/extract", response_model=ExtractionJobStartResponse)
def extract_entities_from_records(
    dataset_id: int,
    labels: LabelsInput,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """
    Kick off extraction for every unreviewed record in the dataset.

    Returns immediately with a job id; progress can be polled via the status endpoint.
    """
    # Verify dataset ownership
    dataset = db.get(Dataset, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )
    if dataset.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this dataset",
        )

    active_job = db.exec(
        select(ExtractionJob)
        .where(ExtractionJob.dataset_id == dataset_id)
        .where(
            (ExtractionJob.status == "pending") | (ExtractionJob.status == "running")
        )
    ).first()
    if active_job is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An extraction job is already running for this dataset",
        )

    records = db.exec(select(Record).where(Record.dataset_id == dataset_id)).all()
    if not records:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No records found for this dataset",
        )
    # TODO
    records_to_process = [r for r in records if not r.reviewed]

    # Activate the globally selected model (or default) and resolve its Model id.
    model_id = resolve_active_model(db)

    # Stale auto-extracted terms are cleared per record inside the background job
    # (run_dataset_extraction_job), right before re-running NER — so a repeat run
    # produces a fresh full extraction, not just for the first run of a model.

    # set current job to False, to set new job to True
    currently_used_job = db.exec(
        select(ExtractionJob)
        .where(ExtractionJob.currently_used == True)  # noqa: E712
        .order_by(ExtractionJob.created_at.desc())
    ).first()
    if currently_used_job is not None:
        currently_used_job.currently_used = False
        db.add(currently_used_job)
        db.commit()

    total = len(records_to_process)
    job = ExtractionJob(
        dataset_id=dataset_id,
        model_id=model_id,
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
        job.updated_at = datetime.now(timezone.utc)
        db.add(job)
        db.commit()

        return ExtractionJobStartResponse(
            job_id=job.id,
            dataset_id=dataset_id,
            total=job.total,
            status=job.status,
        )

    background_tasks.add_task(
        run_dataset_extraction_job,
        job_id=job.id,
        dataset_id=dataset_id,
        labels=labels.labels,
    )

    return ExtractionJobStartResponse(
        job_id=job.id,
        dataset_id=dataset_id,
        total=total,
        status=job.status,
    )


@router.get(
    "/{dataset_id}/records/extract/active",
    response_model=Optional[ExtractionJobStatusResponse],
)
def get_active_extraction_job(
    dataset_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """Return the latest pending/running extraction job for the dataset, or null if none."""
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

    job = db.exec(
        select(ExtractionJob)
        .where(ExtractionJob.dataset_id == dataset_id)
        .where(
            (ExtractionJob.status == "pending") | (ExtractionJob.status == "running")
        )
        .order_by(ExtractionJob.created_at.desc())
    ).first()

    if job is None:
        return None

    return ExtractionJobStatusResponse(
        job_id=job.id,
        dataset_id=job.dataset_id,
        total=job.total,
        completed=job.completed,
        status=job.status,
        error_message=job.error_message,
    )


@router.get(
    "/{dataset_id}/records/extract/{job_id}/status",
    response_model=ExtractionJobStatusResponse,
)
def get_extraction_job_status(
    dataset_id: int,
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """Return progress for a dataset extraction job."""

    dataset = db.get(Dataset, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )
    if dataset.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this dataset",
        )

    job = db.get(ExtractionJob, job_id)
    if job is None or job.dataset_id != dataset_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Extraction job not found for this dataset",
        )

    return ExtractionJobStatusResponse(
        job_id=job.id,
        dataset_id=job.dataset_id,
        total=job.total,
        completed=job.completed,
        status=job.status,
        error_message=job.error_message,
    )


@router.post(
    "/{dataset_id}/records/extract/{job_id}/cancel",
    response_model=MessageOutput,
)
def cancel_extraction_job(
    dataset_id: int,
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """Request cancellation of an extraction job. Already-processed records remain."""

    dataset = db.get(Dataset, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )
    if dataset.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this dataset",
        )

    job = db.get(ExtractionJob, job_id)
    if job is None or job.dataset_id != dataset_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Extraction job not found for this dataset",
        )

    if job.status in {"completed", "failed", "cancelled"}:
        return MessageOutput(message=f"Job already {job.status}")

    job.status = "cancelled"
    job.updated_at = datetime.now(timezone.utc)
    db.add(job)
    db.commit()

    return MessageOutput(message="Cancellation requested")


def run_dataset_extraction_job(job_id: int, dataset_id: int, labels: List[str]):
    """Background task that extracts entities for each unreviewed record."""

    with Session(engine) as session:
        job = session.get(ExtractionJob, job_id)
        if job is None:
            return

        dataset = session.get(Dataset, dataset_id)

        if job.status == "cancelled":
            return

        job.status = "running"
        job.updated_at = datetime.now(timezone.utc)
        session.add(job)
        session.commit()

        records = session.exec(
            select(Record).where(Record.dataset_id == dataset_id)
        ).all()

        # Reprocess every record except reviewed ones and records the user changed
        # manually. A manually created or edited term has
        # automatically_extracted == False, and such records must keep all their
        # terms untouched. Skipping is decided purely from SourceTerm state:
        # a prior version gated on SourceTermEx history, which made a re-run skip
        # every record ever processed, so "delete all entities" + re-extract (or
        # any repeat run) re-extracted nothing.
        unreviewed_records = [r for r in records if not r.reviewed]
        processed_records = []
        records_to_process: List[Record] = []

        for record in unreviewed_records:
            has_manual_term = session.exec(
                select(SourceTerm.id)
                .where(SourceTerm.record_id == record.id)
                .where(SourceTerm.automatically_extracted == False)  # noqa: E712
            ).first()

            if has_manual_term:
                processed_records.append(record)
            else:
                records_to_process.append(record)

        job.total = len(unreviewed_records)
        job.completed = len(processed_records)
        job.updated_at = datetime.now(timezone.utc)
        session.add(job)
        session.commit()

        for record in records_to_process:
            session.refresh(job)
            if job.status == "cancelled":
                job.updated_at = datetime.now(timezone.utc)
                session.add(job)
                session.commit()
                return

            # Clear stale auto-extracted terms before re-running NER so a repeat run
            # yields a fresh full extraction. Manual terms are safe: records with any
            # manual term were excluded from records_to_process above.
            auto_terms = session.exec(
                select(SourceTerm)
                .where(SourceTerm.record_id == record.id)
                .where(SourceTerm.automatically_extracted == True)  # noqa: E712
            ).all()
            for term in auto_terms:
                session.delete(term)
            if auto_terms:
                session.flush()

            request_data = {"medical_text": record.text, "labels": labels}
            try:
                response = requests.post(
                    f"{settings.EXTRACT_HOST}/ner", json=request_data, timeout=300
                )
                response.raise_for_status()
                entities = response.json()
            except requests.RequestException as exc:
                job.status = "failed"
                job.error_message = str(exc)
                job.updated_at = datetime.now(timezone.utc)
                session.add(job)
                session.commit()
                return

            existing_keys = {
                (t.value, t.label, t.start_position, t.end_position)
                for t in session.exec(
                    select(SourceTerm).where(SourceTerm.record_id == record.id)
                ).all()
            }

            seen_in_response = set()

            new_terms: List[SourceTerm] = []
            for entity in entities:
                key = (entity["text"], entity["label"], entity["start"], entity["end"])

                if key in seen_in_response:
                    continue
                seen_in_response.add(key)

                if key in existing_keys:
                    continue
                existing_keys.add(key)
                new_terms.append(
                    SourceTerm(
                        record_id=record.id,
                        value=entity["text"],
                        label=entity["label"],
                        start_position=entity["start"],
                        end_position=entity["end"],
                        score=entity.get("score"),
                        automatically_extracted=True,
                    )
                )

            if new_terms:
                session.add_all(new_terms)
                session.flush()
                link_dates_for_record(session, record, dataset)
                auto_link_entities_for_record(session, record, dataset)

            job.completed += 1
            job.updated_at = datetime.now(timezone.utc)
            session.add(job)
            session.commit()

        job.status = "completed"
        job.updated_at = datetime.now(timezone.utc)
        session.add(job)
        session.commit()


# ================================================
# NER model routes
# ================================================


def get_or_create_model(metadata: dict, db: Session):
    statement = select(Model).where(
        Model.name == metadata["name"], Model.version == metadata["version"]
    )
    existing = db.exec(statement).first()
    if existing:
        return existing

    new_model = Model(name=metadata["name"], version=metadata["version"])

    db.add(new_model)
    db.commit()
    db.refresh(new_model)

    return new_model


def _model_summary(db: Session, model: Model) -> ModelSummary:
    """Build a ModelSummary, including the model's overall macro-F1 if evaluated."""
    per_label = evaluation_service.get_per_label(db, model.id)
    score = evaluation_service.compute_macro_f1(per_label)
    return ModelSummary(
        id=model.id,
        name=model.name,
        version=model.version,
        base_model=model.base_model,
        path=model.path,
        dataset_id=model.dataset_id,
        created_at=model.created_at,
        score=score,
        source=model.source,
        engine=model.engine,
    )


def resolve_active_model(db: Session) -> int:
    """Return the Model id to record extracted terms under, using the GLOBAL
    active model.

    - Globally-selected model (has a path): returns that model's id directly,
      with NO per-call bioner activation. Activation already happened when the
      model was selected via POST /bioner/active-model, so this is a fast
      DB-only lookup in the hot path.
      Known limitation: if the bioner container restarts it reverts to its
      launch default until a model is re-selected in Monitor.
    - Default model (no global selection): queries bioner /model/info to
      identify the currently-loaded model and upserts its metadata row.
      Raises 503 if bioner is unreachable.
    """
    model_db = training_service.get_global_active_model(db)
    if model_db is not None and model_db.path:
        return model_db.id

    # Default model: record under the default's metadata row.
    try:
        info = requests.get(f"{settings.EXTRACT_HOST}/model/info", timeout=30)
        info.raise_for_status()
        metadata = info.json()["model"]
    except requests.RequestException:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Extraction service unavailable",
        )
    return get_or_create_model(metadata, db).id


# ================================================
# NER model selection routes
# ================================================


@router.get("/models", response_model=ModelsOutput)
def list_models(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """List all trained models (instance-global, since the active model is global).

    Excludes per-dataset 'Base model' baseline rows (they are comparison anchors,
    not selectable models). Each summary carries its run id and whether it is the
    global active model.
    """
    active_model_id = training_service.get_app_settings(db).active_model_id
    models = db.exec(
        select(Model)
        .where(Model.path.is_not(None))
        .where(Model.name != training_service.BASELINE_MODEL_NAME)
        .order_by(Model.created_at.desc())
    ).all()
    summaries = []
    for m in models:
        summary = _model_summary(db, m)
        summary.run_id = m.training_run.id if m.training_run else None
        summary.is_active = m.id == active_model_id
        summaries.append(summary)
    return ModelsOutput(models=summaries)


def _default_model_info(default_model, current_engine) -> Optional[DefaultModelInfo]:
    """Build the launch-default descriptor from bioner's raw --model string.

    Local paths are shown as their folder name; HuggingFace ids are shown whole.
    """
    if not default_model:
        return None
    name = (
        os.path.basename(default_model.rstrip("/"))
        if default_model.startswith("/")
        else default_model
    )
    return DefaultModelInfo(name=name, engine=current_engine)


@router.post("/models/rescan", response_model=RescanModelsResponse)
def rescan_models(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """Scan bioner's models dir, reconcile the DB, and return the enriched list.

    This is the ONLY write path for model discovery. On a bioner scan failure it
    is a safe no-op (see ``training_service.discover_models``) and returns the
    current DB list with ``current_engine=None`` (nothing activatable).
    """
    meta = training_service.discover_models(db)
    current_engine = meta["current_engine"]
    scan_by_path = meta["scan_by_path"]

    active_model_id = training_service.get_app_settings(db).active_model_id
    models = db.exec(
        select(Model)
        .where(Model.path.is_not(None))
        .where(Model.name != training_service.BASELINE_MODEL_NAME)
        .order_by(Model.created_at.desc())
    ).all()

    summaries = []
    for m in models:
        base = _model_summary(db, m)
        scanned = scan_by_path.get(m.path.rstrip("/")) if m.path else None
        is_adapter = bool(scanned["is_adapter"]) if scanned else False
        engine = scanned["engine"] if scanned else m.engine
        activatable = (
            current_engine is not None and engine == current_engine and not is_adapter
        )
        summaries.append(
            DiscoveredModelSummary(
                **base.model_dump(),
                is_adapter=is_adapter,
                activatable=activatable,
            )
        )
        summaries[-1].engine = engine
        summaries[-1].run_id = m.training_run.id if m.training_run else None
        summaries[-1].is_active = m.id == active_model_id

    return RescanModelsResponse(
        models=summaries,
        current_engine=current_engine,
        default_model=_default_model_info(meta["default_model"], current_engine),
    )


@router.delete("/models/{model_id}", response_model=MessageOutput)
def delete_model(
    model_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """Delete a model: its on-disk folder (via bioner) and its DB row.

    Works for both trained and rescan-"discovered" models. Refused while the
    model is globally active or any extraction/live-eval job is running. The
    model's job-history rows go with it; a producing TrainingRun is kept as
    history. bioner's 404 (folder already gone) is tolerated so a partially
    failed delete can be retried.
    """
    model = db.get(Model, model_id)
    if model is None:
        raise HTTPException(status_code=404, detail="Model not found")
    if model.source == "baseline" or model.name == training_service.BASELINE_MODEL_NAME:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Baseline comparison rows cannot be deleted",
        )
    if training_service.get_app_settings(db).active_model_id == model.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Model is the active extraction model — switch models first",
        )
    if extraction_lock.any_ner_job_active(db):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An extraction or live-eval job is running — try again later",
        )

    # Local model folders live under bioner's models dir (absolute paths); HF-id
    # rows have nothing on disk. Folder first: if it fails nothing has changed,
    # and if the later DB delete fails a rescan re-adds the row for a retry.
    if model.path and model.path.startswith("/"):
        dir_name = os.path.basename(model.path.rstrip("/"))
        try:
            bioner_client.delete_model_dir(dir_name)
        except requests.HTTPError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=bioner_client.http_error_detail(exc)
                or "Extraction service refused to delete the model folder",
            )
        except requests.RequestException:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Extraction service unavailable",
            )

    training_service.delete_model(db, model)
    return MessageOutput(message="deleted")


@router.get("/models/{model_id}/detail", response_model=ModelDetailResponse)
def model_detail(
    model_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """Per-model detail: training datasets, snapshot stats, labels, and the
    base-vs-trained per-label evaluation (same split, the only valid comparison)."""
    model = db.get(Model, model_id)
    if model is None:
        raise HTTPException(status_code=404, detail="Model not found")
    run = model.training_run
    per_label_trained = _scores_only(evaluation_service.get_per_label(db, model.id))
    per_label_baseline = {}
    train_ids: list[int] = []
    eval_ids: list[int] = []
    train_stats = None
    labels: list[str] = []
    if run is not None:
        train_ids = training_service.get_dataset_ids(db, run.id, role="train") or [
            run.dataset_id
        ]
        eval_ids = training_service.get_dataset_ids(db, run.id, role="eval") or []
        train_stats = run.train_stats
        labels = run.labels or []
        baseline = training_service.get_baseline_model(db, run.dataset_id)
        if baseline is not None:
            per_label_baseline = _scores_only(
                evaluation_service.get_per_label(db, baseline.id)
            )
    return ModelDetailResponse(
        model_id=model.id,
        run_id=run.id if run else None,
        base_model=model.base_model,
        train_dataset_ids=train_ids,
        eval_dataset_ids=eval_ids,
        train_stats=train_stats,
        labels=labels,
        per_label_trained=per_label_trained,
        per_label_baseline=per_label_baseline,
    )


def _activate_on_bioner(model_path: Optional[str]) -> None:
    """Hot-swap bioner to the given model path (None = revert to launch default).

    Route-handler wrapper around ``bioner_client.activate_model``: bioner's own
    rejection (400, e.g. the artifact no longer exists on disk) is forwarded
    with its message; anything else surfaces as a 503.
    """
    try:
        bioner_client.activate_model(model_path)
    except requests.HTTPError as exc:
        detail = bioner_client.http_error_detail(exc)
        if exc.response is not None and exc.response.status_code == 400 and detail:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Extraction service unavailable",
        )
    except requests.RequestException:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Extraction service unavailable",
        )


@router.get("/active-model", response_model=ActiveModelResponse)
def get_active_model(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """Return the GLOBAL active extraction model (null = bioner default)."""
    model = training_service.get_global_active_model(db)
    active = _model_summary(db, model) if model is not None else None
    return ActiveModelResponse(active_model=active)


@router.post("/active-model", response_model=ActiveModelResponse)
def set_active_model(
    payload: SetActiveModelRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """Set/clear the GLOBAL active extraction model and hot-swap bioner.

    Blocked (409) while any extraction OR live-eval job is active instance-wide so
    an in-flight job's pinned model can't be undermined (live eval hot-swaps and
    restores this same global model).
    """
    if extraction_lock.any_ner_job_active(db):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot change the model while an extraction job is running",
        )

    if payload.model_id is None:
        _activate_on_bioner(None)
        training_service.set_global_active_model(db, None)
        return ActiveModelResponse(active_model=None)

    model = db.get(Model, payload.model_id)
    if model is None:
        raise HTTPException(status_code=404, detail="Model not found")
    if model.path is None:
        raise HTTPException(
            status_code=400,
            detail="Model has no trained artifact to use for extraction",
        )
    _activate_on_bioner(model.path)
    training_service.set_global_active_model(db, model.id)
    return ActiveModelResponse(active_model=_model_summary(db, model))


# ================================================
# Training / monitoring routes
# ================================================


def _bioner_conflict_detail(resp: requests.Response) -> dict:
    """Extract bioner's 409 conflict ``detail`` for pass-through to the client.

    bioner returns ``{"detail": {"error": "TRAINING_BUSY" | "TRAINING_STOPPING",
    "message": ..., "suggestion": ...}}``. Forward that structured detail so the
    frontend can branch on the error code; fall back to a generic busy detail if
    the body isn't shaped as expected.
    """
    try:
        detail = resp.json().get("detail")
    except ValueError:
        detail = None
    if isinstance(detail, dict) and detail.get("error"):
        return detail
    return {
        "error": "TRAINING_BUSY",
        "message": "Another training job is already running",
        "suggestion": "Wait for current training to finish",
    }


TRAINER_DIED_MESSAGE = (
    "Training stopped unexpectedly — the training process was terminated, most "
    "likely because the computer ran out of memory (RAM). Try a smaller base "
    "model, a lower batch size (under Advanced), or fewer training records; if "
    "you run Docker Desktop, allocating it more memory also helps."
)

# Runs younger than this are never probed: bioner registers a run shortly
# after start, and probing inside that window would misread it as dead.
RECONCILE_GRACE_SECONDS = 120


def _reconcile_run_liveness(db: Session, run: TrainingRun) -> bool:
    """Verify a DB-active run is still alive on bioner; mark it failed if not.

    Returns False when the run was just marked failed. bioner being
    unreachable means *unknown*, not dead — the run is left untouched.
    """
    if run.status not in ("pending", "running"):
        return True
    created = run.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) - created < timedelta(
        seconds=RECONCILE_GRACE_SECONDS
    ):
        return True
    try:
        snapshot = bioner_client.get_training_status(run.id)
    except requests.RequestException:
        return True
    if snapshot is not None and snapshot.get("status") == "running":
        return True
    training_service.fail_run(db, run.id, TRAINER_DIED_MESSAGE)
    return False


@router.post("/training/start", response_model=TrainingStartResponse)
def start_training(
    req: GLiNERTrainingRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    # ``req.dataset_ids`` is resolved + de-duplicated by the schema validator.
    train_ids = req.dataset_ids
    eval_ids = req.eval_dataset_ids

    # Verify the caller owns every selected dataset (train + eval).
    for dsid in [*train_ids, *eval_ids]:
        dataset = db.get(Dataset, dsid)
        if dataset is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Dataset {dsid} not found",
            )
        if dataset.user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Not authorized to access dataset {dsid}",
            )

    # Reconcile stale "active" runs first: a run left in pending/running whose
    # trainer is no longer alive on bioner (e.g. after a bioner restart or a
    # crashed training thread) would otherwise wedge its datasets forever. Ask
    # bioner whether each still-active run is genuinely running; mark the rest
    # failed so a new run can start.
    for run in training_service.get_active_runs_for_datasets(db, train_ids):
        _reconcile_run_liveness(db, run)

    # Reject a second genuinely-concurrent run touching any of the datasets.
    if training_service.has_active_run_for_datasets(db, train_ids):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A training run is already active for one of these datasets",
        )

    train_stats_snapshot = {
        "train_dataset_ids": train_ids,
        "eval_dataset_ids": eval_ids,
        **_compute_dataset_stats(db, train_ids),
        "val_ratio": req.val_ratio,
    }
    run = training_service.create_run(
        db,
        dataset_ids=train_ids,
        base_model=req.base_model,
        labels=req.labels,
        val_ratio=req.val_ratio,
        eval_dataset_ids=eval_ids,
        train_stats=train_stats_snapshot,
    )
    try:
        training_data = gliner_data_service.load_reviewed_training_data(
            db, train_ids, req.labels
        )
        # Separate eval datasets override the held-out split when provided.
        eval_data = (
            gliner_data_service.load_reviewed_training_data(db, eval_ids, req.labels)
            if eval_ids
            else []
        )
        bioner_client.start_training(
            {
                "run_id": run.id,
                "base_model": req.base_model,
                "training_data": training_data,
                "eval_data": eval_data,
                "val_ratio": req.val_ratio,
                "num_epochs": req.num_epochs,
                "learning_rate": req.learning_rate,
                "train_batch_size": req.train_batch_size,
            }
        )
    except requests.HTTPError as exc:
        # A 409 from bioner means the trainer slot is occupied: another run is
        # genuinely active (TRAINING_BUSY) or a stopped run hasn't wound down yet
        # (TRAINING_STOPPING). Surface the machine-readable reason so the client
        # can show the right message (and retry on STOPPING) instead of the run
        # silently landing as "failed".
        resp = exc.response
        if resp is not None and resp.status_code == status.HTTP_409_CONFLICT:
            training_service.fail_run(db, run.id, "trainer busy: run not started")
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=_bioner_conflict_detail(resp),
            ) from exc
        training_service.fail_run(db, run.id, f"failed to start trainer: {exc}")
    except Exception as exc:  # trainer unreachable -> mark failed, but still return run
        training_service.fail_run(db, run.id, f"failed to start trainer: {exc}")
    return TrainingStartResponse(run_id=run.id)


@router.post("/training/stop/{run_id}", response_model=MessageOutput)
def stop_training(
    run_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    training_service.stop_run(db, run_id)
    try:
        bioner_client.stop_training(run_id)
    except Exception:
        pass
    return MessageOutput(message="stopped")


def _compute_dataset_stats(db: Session, dataset_ids: list) -> dict:
    """Compute aggregated stats across the given dataset IDs.

    Returns both TOTAL stats (every record/term in the datasets) and REVIEWED
    stats (only the training-eligible subset). Training and evaluation use only
    reviewed records with valid character offsets — see
    ``gliner_data_service.load_reviewed_training_data`` — so the reviewed_*
    figures mirror what actually trains.

    Keys:
        ``record_count`` / ``term_count`` / ``label_distribution`` — TOTAL over
            the whole dataset (kept as-is for back-compat).
        ``reviewed_record_count`` / ``reviewed_term_count`` /
            ``reviewed_label_distribution`` — the reviewed, training-eligible
            subset (``Record.reviewed`` is True and the term has non-null
            ``start_position`` and ``end_position``).
    """
    # --- TOTAL: whole dataset ---
    record_count = db.exec(
        select(func.count(Record.id)).where(Record.dataset_id.in_(dataset_ids))
    ).one()
    term_count = db.exec(
        select(func.count(SourceTerm.id))
        .join(Record, Record.id == SourceTerm.record_id)
        .where(Record.dataset_id.in_(dataset_ids))
    ).one()
    rows = db.exec(
        select(SourceTerm.label, func.count(SourceTerm.id))
        .join(Record, Record.id == SourceTerm.record_id)
        .where(Record.dataset_id.in_(dataset_ids))
        .group_by(SourceTerm.label)
    ).all()

    # --- REVIEWED: mirror the trainer's predicate exactly ---
    reviewed_record_count = db.exec(
        select(func.count(Record.id))
        .where(Record.dataset_id.in_(dataset_ids))
        .where(Record.reviewed == True)  # noqa: E712
    ).one()
    reviewed_term_where = (
        Record.dataset_id.in_(dataset_ids),
        Record.reviewed == True,  # noqa: E712
        SourceTerm.start_position.is_not(None),
        SourceTerm.end_position.is_not(None),
    )
    reviewed_term_count = db.exec(
        select(func.count(SourceTerm.id))
        .join(Record, Record.id == SourceTerm.record_id)
        .where(*reviewed_term_where)
    ).one()
    reviewed_rows = db.exec(
        select(SourceTerm.label, func.count(SourceTerm.id))
        .join(Record, Record.id == SourceTerm.record_id)
        .where(*reviewed_term_where)
        .group_by(SourceTerm.label)
    ).all()

    return {
        "record_count": record_count,
        "term_count": term_count,
        "label_distribution": {label: count for label, count in rows},
        "reviewed_record_count": reviewed_record_count,
        "reviewed_term_count": reviewed_term_count,
        "reviewed_label_distribution": {label: count for label, count in reviewed_rows},
    }


def _full_stats_response(stats: dict) -> FullStatsResponse:
    """Serialize ``_compute_dataset_stats`` output into the API response."""
    return FullStatsResponse(
        totalRecords=stats["record_count"],
        totalTerms=stats["term_count"],
        labelDistribution=stats["label_distribution"],
        reviewedRecords=stats["reviewed_record_count"],
        reviewedTerms=stats["reviewed_term_count"],
        reviewedLabelDistribution=stats["reviewed_label_distribution"],
    )


@router.get("/datasets/{dataset_id}/full-stats", response_model=FullStatsResponse)
def full_stats(
    dataset_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    return _full_stats_response(_compute_dataset_stats(db, [dataset_id]))


@router.post("/datasets/full-stats", response_model=FullStatsResponse)
def full_stats_multi(
    req: FullStatsRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """Aggregate record/term counts and label distribution across datasets."""
    return _full_stats_response(_compute_dataset_stats(db, req.dataset_ids))


def _run_summary(db: Session, run: TrainingRun) -> TrainingRunSummary:
    """Build an enriched run summary, including artifact path and macro-F1 score."""
    path = None
    score = None
    if run.model_id is not None:
        model = db.get(Model, run.model_id)
        if model is not None:
            path = model.path
        per_label = evaluation_service.get_per_label(db, run.model_id)
        score = evaluation_service.compute_macro_f1(per_label)
    return TrainingRunSummary(
        run_id=run.id,
        status=run.status,
        name=run.name,
        base_model=run.base_model,
        labels=run.labels or [],
        val_ratio=run.val_ratio,
        created_at=run.created_at,
        error_message=run.error_message,
        path=path,
        model_id=run.model_id,
        score=score,
        preferred=run.preferred,
    )


def _get_owned_run(db: Session, run_id: int, current_user: User) -> TrainingRun:
    """Fetch a run and verify the caller owns its dataset, else raise 404/403."""
    run = db.get(TrainingRun, run_id)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Run not found"
        )
    dataset = db.get(Dataset, run.dataset_id)
    if dataset is not None and dataset.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this run",
        )
    return run


@router.get("/runs/active", response_model=Optional[ActiveTrainingRunResponse])
def active_run(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """Return the current in-flight (pending/running) training run, or null.

    Lets the Monitor page rehydrate live progress after navigating away and back
    or after a full page reload: the loss curve, step counters and epoch bounds
    are returned in one call so the UI can resume without waiting for the next
    websocket event. Only surfaces a run the caller owns.
    """
    run = training_service.get_active_run(db)
    if run is None:
        return None
    dataset = db.get(Dataset, run.dataset_id)
    if dataset is not None and dataset.user_id != current_user.id:
        return None

    train_ids = training_service.get_dataset_ids(db, run.id, role="train") or [
        run.dataset_id
    ]

    # The trainer may have died without a final event (e.g. OOM-killed);
    # surface the failure once so the Monitor shows why instead of a stuck run.
    if not _reconcile_run_liveness(db, run):
        db.refresh(run)
        return ActiveTrainingRunResponse(
            run_id=run.id,
            dataset_ids=train_ids,
            status="failed",
            error_message=run.error_message,
        )
    metrics = training_service.get_run_metrics(db, run.id)
    ordered = sorted(
        metrics,
        key=lambda m: (m.step is None, m.step if m.step is not None else 0, m.epoch),
    )
    stats = run.train_stats or {}
    steps = [m.step for m in metrics if m.step is not None]
    epochs = [m.epoch for m in metrics if m.epoch is not None]
    current_step = max(steps) if steps else None
    return ActiveTrainingRunResponse(
        run_id=run.id,
        dataset_ids=train_ids,
        status=run.status,
        total_steps=stats.get("total_steps"),
        current_step=current_step,
        num_epochs=stats.get("num_epochs"),
        current_epoch=max(epochs) if epochs else None,
        metrics=[
            TrainingMetricPoint(
                epoch=m.epoch, loss=m.loss, step=m.step, eval_loss=m.eval_loss
            )
            for m in ordered
        ],
        phase=training_service.derive_training_phase(db, run, current_step),
    )


@router.get("/datasets/{dataset_id}/runs", response_model=TrainingRunsOutput)
def list_runs(
    dataset_id: int,
    page: int = Query(1, ge=1, description="Page number (newest first)"),
    limit: int = Query(20, ge=1, le=100, description="Runs per page"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """Return a dataset's training runs, newest first, paginated."""
    total = db.exec(
        select(func.count(TrainingRun.id)).where(TrainingRun.dataset_id == dataset_id)
    ).one()
    offset = (page - 1) * limit
    runs = db.exec(
        select(TrainingRun)
        .where(TrainingRun.dataset_id == dataset_id)
        .order_by(TrainingRun.id.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    return TrainingRunsOutput(
        runs=[_run_summary(db, r) for r in runs],
        pagination=create_pagination_metadata(total, limit, offset),
    )


@router.patch("/runs/{run_id}", response_model=TrainingRunSummary)
def update_run(
    run_id: int,
    payload: TrainingRunUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """Rename a run and/or mark it as the dataset's preferred run."""
    _get_owned_run(db, run_id, current_user)
    run = training_service.update_run(
        db, run_id, name=payload.name, preferred=payload.preferred
    )
    return _run_summary(db, run)


@router.delete("/runs/{run_id}", response_model=MessageOutput)
def delete_run(
    run_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """Delete a run and its dependent metrics/model/evaluation rows."""
    _get_owned_run(db, run_id, current_user)
    training_service.delete_run(db, run_id)
    return MessageOutput(message="deleted")


def _scores_only(per_label: dict) -> dict:
    """Drop the heavy per-label ``examples`` arrays, keeping scalar scores/counts.

    Used by the score-oriented endpoints (single-run bars, heatmap) so they don't
    ship example-error text; the full data is served by the error-analysis route.
    """
    return {
        label: {k: v for k, v in metrics.items() if k != "examples"}
        if isinstance(metrics, dict)
        else metrics
        for label, metrics in per_label.items()
    }


@router.get("/runs/{run_id}/evaluation", response_model=RunEvaluationResponse)
def run_evaluation(
    run_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    run = db.get(TrainingRun, run_id)
    per_label = {}
    if run is not None and run.model_id is not None:
        per_label = _scores_only(evaluation_service.get_per_label(db, run.model_id))
    return RunEvaluationResponse(run_id=run_id, per_label=per_label)


@router.get("/runs/{run_id}/error-analysis", response_model=RunErrorAnalysisResponse)
def run_error_analysis(
    run_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """Return per-label error analysis for a run: precision/recall, false-positive
    and false-negative counts, and a bounded sample of concrete example errors.

    The data is read from the run model's stored per-label evaluation JSON. Runs
    trained before error analysis was added have no such data; for those
    ``available`` is False and ``per_label`` is empty.
    """
    run = _get_owned_run(db, run_id, current_user)

    per_label_raw = (
        evaluation_service.get_per_label(db, run.model_id) if run.model_id else {}
    )
    # Newer runs always carry fp/fn/examples; their presence marks the data as
    # available. Older runs only have F1/precision/recall scores.
    available = any(
        isinstance(m, dict) and ("fp" in m or "examples" in m)
        for m in per_label_raw.values()
    )

    per_label = {}
    if available:
        for label, m in per_label_raw.items():
            if not isinstance(m, dict):
                continue
            per_label[label] = LabelErrorAnalysis(
                precision=m.get("precision"),
                recall=m.get("recall"),
                fp=m.get("fp"),
                fn=m.get("fn"),
                examples=m.get("examples") or [],
            )

    return RunErrorAnalysisResponse(
        run_id=run_id, available=available, per_label=per_label
    )


@router.get("/runs/{run_id}/metrics", response_model=List[TrainingMetricPoint])
def run_metrics(
    run_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """Return a run's loss curve ordered by step (nulls last) then epoch."""
    metrics = training_service.get_run_metrics(db, run_id)
    ordered = sorted(
        metrics,
        key=lambda m: (m.step is None, m.step if m.step is not None else 0, m.epoch),
    )
    return [
        TrainingMetricPoint(
            epoch=m.epoch, loss=m.loss, step=m.step, eval_loss=m.eval_loss
        )
        for m in ordered
    ]


@router.get("/datasets/{dataset_id}/runs/evaluations")
def dataset_runs_evaluations(
    dataset_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    out = []

    # Prepend the default extraction model as a baseline (run_id 0, not a real
    # run) so trained runs can be compared against the starting point. Only
    # included once it has been evaluated on this dataset's eval split.
    baseline = training_service.get_baseline_model(db, dataset_id)
    if baseline is not None:
        baseline_per_label = _scores_only(
            evaluation_service.get_per_label(db, baseline.id)
        )
        if baseline_per_label:
            out.append(
                {
                    "run_id": 0,
                    "name": "Base model",
                    "is_baseline": True,
                    "per_label": baseline_per_label,
                }
            )

    runs = db.exec(
        select(TrainingRun).where(TrainingRun.dataset_id == dataset_id)
    ).all()
    for r in runs:
        per_label = (
            _scores_only(evaluation_service.get_per_label(db, r.model_id))
            if r.model_id
            else {}
        )
        out.append({"run_id": r.id, "per_label": per_label})
    return out


@router.websocket("/ws/training")
async def ws_training(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(websocket)
