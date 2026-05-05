import requests
from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlmodel import Session, select

from app.core.database import Dataset, User, engine, get_session
from app.core.settings import settings
from app.interfaces import Entity, LabelsInput, NERRequest
from app.library.record_processing import link_dates_for_record
from app.models_db import ExtractionJob, Record, SourceTerm
from app.routes.v1.auth import get_current_user
from app.schemas import (
    ExtractionJobStartResponse,
    ExtractionJobStatusResponse,
    MessageOutput,
)

router = APIRouter(tags=["BioNER"])


@router.post("/extract", response_model=List[Entity])
def extract_entities(
    request: NERRequest,
):
    """
    Extract named entities from medical text using the BioNER service.
    """

    # TODO: Must not allow it to be accessible without authentication
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

    existing_keys = {
        (t.value, t.label, t.start_position, t.end_position)
        for t in db.exec(
            select(SourceTerm).where(SourceTerm.record_id == record_id)
        ).all()
    }

    new_terms: List[SourceTerm] = []
    for entity in entities:
        key = (
            entity["text"],
            entity["label"],
            entity["start"],
            entity["end"],
        )
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

    records = db.exec(select(Record).where(Record.dataset_id == dataset_id)).all()
    if not records:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No records found for this dataset",
        )

    records_to_process = [r for r in records if not r.reviewed]
    total = len(records_to_process)

    job = ExtractionJob(
        dataset_id=dataset_id,
        total=total,
        completed=0,
        status="pending",
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
            total=total,
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

        # Skip reviewed records and records already containing automatically extracted terms
        unreviewed_records = [r for r in records if not r.reviewed]
        processed_records = []
        records_to_process: List[Record] = []

        for record in unreviewed_records:
            has_auto = session.exec(
                select(SourceTerm.id)
                .where(SourceTerm.record_id == record.id)
                .where(SourceTerm.automatically_extracted == True)  # noqa: E712
            ).first()

            if has_auto:
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

            new_terms: List[SourceTerm] = []
            for entity in entities:
                key = (
                    entity["text"],
                    entity["label"],
                    entity["start"],
                    entity["end"],
                )
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

            job.completed += 1
            job.updated_at = datetime.now(timezone.utc)
            session.add(job)
            session.commit()

        job.status = "completed"
        job.updated_at = datetime.now(timezone.utc)
        session.add(job)
        session.commit()


# ================================================
# Model Management
# ================================================


@router.post("/models/switch", status_code=status.HTTP_200_OK)
def switch_model(
    engine: str,
    model: str,
    adapter_model: str | None = None,
    use_gpu: bool = False,
):
    try:
        payload = {
            "engine": engine,
            "model": model,
            "adapter_model": adapter_model,
            "use_gpu": use_gpu,
        }
        response = requests.post(
            f"{settings.EXTRACT_HOST}/models/switch",
            json=payload,
            timeout=300,
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 400:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=e.response.text,
            )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="BioNER service unavailable or returned an error",
        )
    except requests.RequestException:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="BioNER service unavailable",
        )


@router.get("/models/current")
def get_current_model():
    try:
        response = requests.get(
            f"{settings.EXTRACT_HOST}/models/current",
            timeout=10,
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="BioNER service unavailable",
        )


@router.get("/models/health")
def check_model_health():
    try:
        response = requests.get(
            f"{settings.EXTRACT_HOST}/models/health",
            timeout=10,
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="BioNER service unavailable",
        )


@router.get("/models/available")
def list_available_models():
    try:
        response = requests.get(
            f"{settings.EXTRACT_HOST}/models/available",
            timeout=10,
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="BioNER service unavailable",
        )