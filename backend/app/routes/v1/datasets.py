from datetime import datetime, timezone
import json as _json
import logging
import os
import re
from typing import List, Optional, Union
from uuid import uuid4

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
    File,
    UploadFile,
    Form,
    BackgroundTasks,
)
from fastapi.responses import StreamingResponse
from sqlmodel import Session, select, func, update
from collections import defaultdict, Counter

from hdbscan import HDBSCAN

from app.core.database import engine, get_session
from app.core.model_registry import model_registry
from app.core.settings import settings
from app.models_db import (
    Dataset,
    Record,
    SourceTerm,
    SourceTermLink,
    User,
    Cluster,
    ClusterJob,
    SourceToConceptMap,
    ProcessingStatus,
)
from app.library.file_parser import parse_records_file
from app.library.record_processing import (
    bulk_insert_records_with_segments,
    regenerate_record_segments,
    link_dates_for_record,
)
from app.routes.v1.auth import get_current_user
from app.schemas import (
    DatasetResponse,
    DatasetUploadResponse,
    DatasetStatisticsResponse,
    DatasetOverviewResponse,
    ClusteringStatsResponse,
    MappingStatsResponse,
    DatasetsOutput,
    DatasetOutput,
    RecordCreate,
    RecordResponse,
    RecordsOutput,
    RecordOutput,
    SourceTermCreate,
    SourceTermOutput,
    SourceTermsOutput,
    SourceTermResponse,
    SourceTermLinkResponse,
    MessageOutput,
    PaginationParams,
    ClusteredTerm,
    ClusterCreate,
    ClustersStatisticsOutput,
    ClusterResponse,
    ClusterMerge,
    ClusterReviewLabelRequest,
    ClusterJobStartResponse,
    ClusterJobStatusResponse,
    create_pagination_metadata,
)

from app.library.file_parser import (
    download_annotated_dataset,
    build_clusters_download_json,
)

from app.utils.value_typing import (
    detect_value_type,
    normalize_date_to_key,
    normalize_measure_to_key,
)
from app.utils.vector_math import cosine_similarity as _cosine_similarity
from app.utils.vector_math import mean_vector as _compute_centroid

# ================================================
# Route definitions
# ================================================

router = APIRouter()

logger = logging.getLogger(__name__)

# ================================================
# Helper functions
# ================================================


def verify_dataset_ownership(dataset: Dataset, user_id: int):
    """Verify that the user owns the dataset."""
    if dataset.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this dataset",
        )


# ================================================
# Datasets routes
# ================================================


@router.get(
    "/",
    response_model=DatasetsOutput,
    status_code=status.HTTP_200_OK,
    summary="List all datasets",
    description="Retrieves a list of all datasets owned by the authenticated user",
    response_description="List of datasets with their metadata",
)
def get_datasets(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
    pagination: PaginationParams = Depends(),
):
    # Get total count (exclude DELETED)
    total = db.exec(
        select(func.count())
        .select_from(Dataset)
        .where(Dataset.user_id == current_user.id)
        .where(Dataset.status != ProcessingStatus.DELETED)
    ).one()

    # Get paginated datasets (exclude DELETED)
    datasets = db.exec(
        select(Dataset)
        .where(Dataset.user_id == current_user.id)
        .where(Dataset.status != ProcessingStatus.DELETED)
        .order_by(Dataset.id)
        .offset(pagination.offset)
        .limit(pagination.limit)
    ).all()

    dataset_responses = [
        DatasetResponse(
            id=dataset.id,
            name=dataset.name,
            uploaded=dataset.uploaded,
            last_modified=dataset.last_modified,
            labels=dataset.labels,
            label_relations=dataset.label_relations or [],
            date_label=dataset.date_label,
            status=dataset.status,
            error_message=dataset.error_message,
            record_count=db.query(func.count(Record.id))
            .filter(Record.dataset_id == dataset.id)
            .scalar(),
        )
        for dataset in datasets
    ]

    return DatasetsOutput(
        datasets=dataset_responses,
        pagination=create_pagination_metadata(
            total, pagination.limit, pagination.offset
        ),
    )


@router.post(
    "/",
    response_model=DatasetUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new dataset",
    description="Creates a new dataset with its associated records",
    response_description="The created dataset with its metadata",
)
async def create_dataset(
    background_tasks: BackgroundTasks,
    name: str = Form(...),
    labels: str = Form(...),
    label_relations: Optional[str] = Form(None),
    date_label: Optional[str] = Form(None),
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    file_name = file.filename.lower()
    if not file_name.endswith(".csv") and not file_name.endswith(".json"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported file type.",
        )

    # Reject obviously oversized uploads via Content-Length header
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if file.size and file.size > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large. Maximum size is {settings.MAX_UPLOAD_SIZE_MB} MB.",
        )

    # save file to disk (preserving original extension for the parser)
    suffix = os.path.splitext(file.filename)[1].lower()
    file_path = await save_upload_to_disk(file, suffix)

    label_list = [label.strip() for label in labels.split(",") if label.strip()]
    if not label_list:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one non-empty label is required.",
        )
    parsed_relations: list = []
    if label_relations:
        try:
            parsed_relations = _json.loads(label_relations)
        except Exception:
            parsed_relations = []
    # start background ingestion
    background_tasks.add_task(
        ingest_dataset_background,
        file_path,
        name,
        label_list,
        current_user.id,
        date_label,
        parsed_relations,
    )

    dataset_response = DatasetUploadResponse(
        status=ProcessingStatus.PENDING,
        message="Record upload successfully started background task",
    )
    return dataset_response


def ingest_dataset_background(
    file_path: str,
    name: str,
    label_list: list,
    user_id: int,
    date_label: Optional[str] = None,
    label_relations: Optional[list] = None,
):
    db = Session(engine)

    # create a new Dataset
    REQUIRED_COLUMNS = ["text", "patient_id", "visit_date"]
    dataset = Dataset(
        name=name,
        labels=label_list,
        label_relations=label_relations or [],
        user_id=user_id,
        date_label=date_label,
    )
    db.add(dataset)
    db.commit()
    # Refresh the instance so database now has its generated ID
    db.refresh(dataset)

    dataset_id = dataset.id
    default_visit_date = None

    try:
        BATCH_SIZE = 2000
        batch = []
        total = 0
        for record in parse_records_file(
            file_path,
            REQUIRED_COLUMNS,
            default_visit_date=default_visit_date,
        ):
            record.dataset_id = dataset_id
            batch.append(record)

            if len(batch) >= BATCH_SIZE:
                chunk_len = len(batch)
                bulk_insert_records_with_segments(db, batch)
                total += chunk_len
                batch.clear()
                print("Rows saved:", total)

        if batch:
            chunk_len = len(batch)
            bulk_insert_records_with_segments(db, batch)
            total += chunk_len
            batch.clear()
            print("All rows saved.")

        db.exec(
            update(Dataset)
            .where(Dataset.id == dataset_id)
            .values(status=ProcessingStatus.DONE)
        )
        db.commit()

    except Exception as e:
        import traceback

        traceback.print_exc()
        # failure cleanup
        db.rollback()

        error_msg = str(e)

        db.exec(
            update(Dataset)
            .where(Dataset.id == dataset_id)
            .values(status=ProcessingStatus.FAILED, error_message=error_msg)
        )
        db.commit()

    finally:
        db.close()


async def save_upload_to_disk(file: UploadFile, suffix: str) -> str:
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    path = f"/tmp/{uuid4()}{suffix}"
    total = 0

    with open(path, "wb") as out:
        # read 1 MB at a time
        while chunk := await file.read(1024 * 1024):
            total += len(chunk)
            if total > max_bytes:
                os.unlink(path)
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=f"File too large. Maximum size is {settings.MAX_UPLOAD_SIZE_MB} MB.",
                )
            out.write(chunk)

    return path


@router.get(
    "/{dataset_id}",
    response_model=DatasetOutput,
    status_code=status.HTTP_200_OK,
    summary="Get a specific dataset",
    description="Retrieves a single dataset by its ID",
    response_description="The requested dataset with its metadata",
)
def get_dataset(
    dataset_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    dataset = db.get(Dataset, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
        )
    verify_dataset_ownership(dataset, current_user.id)
    dataset_response = DatasetResponse(
        id=dataset.id,
        name=dataset.name,
        uploaded=dataset.uploaded,
        last_modified=dataset.last_modified,
        labels=dataset.labels,
        label_relations=dataset.label_relations or [],
        date_label=dataset.date_label,
        status=dataset.status,
        error_message=dataset.error_message,
        record_count=db.query(func.count(Record.id))
        .filter(Record.dataset_id == dataset.id)
        .scalar(),
    )
    return DatasetOutput(dataset=dataset_response)


@router.get(
    "/{dataset_id}/statistics",
    response_model=DatasetStatisticsResponse,
    status_code=status.HTTP_200_OK,
    summary="Get dataset statistics",
    description="Retrieves statistics for a dataset including record counts and processing status",
    response_description="Dataset statistics",
)
def get_dataset_stats(
    dataset_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    dataset = db.get(Dataset, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
        )
    verify_dataset_ownership(dataset, current_user.id)

    # Total records count
    total_records = db.exec(
        select(func.count()).select_from(Record).where(Record.dataset_id == dataset_id)
    ).one()

    # Processed count: records with at least one source term
    processed_count = db.exec(
        select(func.count(func.distinct(Record.id)))
        .select_from(Record)
        .join(SourceTerm, Record.id == SourceTerm.record_id)
        .where(Record.dataset_id == dataset_id)
    ).one()

    # Pending review count: records that have not been reviewed yet
    pending_review_count = db.exec(
        select(func.count())
        .select_from(Record)
        .where(Record.dataset_id == dataset_id)
        .where(Record.reviewed == False)  # noqa: E712
    ).one()

    # Total extracted terms count
    extracted_terms_count = db.exec(
        select(func.count())
        .select_from(SourceTerm)
        .join(Record, SourceTerm.record_id == Record.id)
        .where(Record.dataset_id == dataset_id)
    ).one()

    return DatasetStatisticsResponse(
        total_records=total_records,
        processed_count=processed_count,
        pending_review_count=pending_review_count,
        extracted_terms_count=extracted_terms_count,
    )


@router.get(
    "/{dataset_id}/overview",
    response_model=DatasetOverviewResponse,
    status_code=status.HTTP_200_OK,
    summary="Get dataset overview",
    description="Retrieves comprehensive overview with dataset info, statistics, clustering stats, and mapping stats",
    response_description="Dataset overview",
)
def get_dataset_overview(
    dataset_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    dataset = db.get(Dataset, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
        )
    verify_dataset_ownership(dataset, current_user.id)

    # Get dataset response
    dataset_response = DatasetResponse(
        id=dataset.id,
        name=dataset.name,
        uploaded=dataset.uploaded,
        last_modified=dataset.last_modified,
        labels=dataset.labels,
        label_relations=dataset.label_relations or [],
        date_label=dataset.date_label,
        status=dataset.status,
        error_message=dataset.error_message,
        record_count=len(dataset.records),
    )

    # Get dataset statistics
    total_records = db.exec(
        select(func.count()).select_from(Record).where(Record.dataset_id == dataset_id)
    ).one()

    processed_count = db.exec(
        select(func.count(func.distinct(Record.id)))
        .select_from(Record)
        .join(SourceTerm, Record.id == SourceTerm.record_id)
        .where(Record.dataset_id == dataset_id)
    ).one()

    pending_review_count = db.exec(
        select(func.count())
        .select_from(Record)
        .where(Record.dataset_id == dataset_id)
        .where(Record.reviewed == False)  # noqa: E712
    ).one()

    extracted_terms_count = db.exec(
        select(func.count())
        .select_from(SourceTerm)
        .join(Record, SourceTerm.record_id == Record.id)
        .where(Record.dataset_id == dataset_id)
    ).one()

    stats = DatasetStatisticsResponse(
        total_records=total_records,
        processed_count=processed_count,
        pending_review_count=pending_review_count,
        extracted_terms_count=extracted_terms_count,
    )

    # Get clustering statistics
    total_clusters = db.exec(
        select(func.count())
        .select_from(Cluster)
        .where(Cluster.dataset_id == dataset_id)
    ).one()

    clustered_terms = db.exec(
        select(func.count())
        .select_from(SourceTerm)
        .join(Record, SourceTerm.record_id == Record.id)
        .where(Record.dataset_id == dataset_id)
        .where(SourceTerm.cluster_id.isnot(None))
    ).one()

    unclustered_terms = db.exec(
        select(func.count())
        .select_from(SourceTerm)
        .join(Record, SourceTerm.record_id == Record.id)
        .where(Record.dataset_id == dataset_id)
        .where(SourceTerm.cluster_id.is_(None))
    ).one()

    clustering_stats = ClusteringStatsResponse(
        total_clusters=total_clusters,
        clustered_terms=clustered_terms,
        unclustered_terms=unclustered_terms,
    )

    # Get mapping statistics
    mapped_clusters = db.exec(
        select(func.count(func.distinct(SourceToConceptMap.cluster_id)))
        .select_from(SourceToConceptMap)
        .join(Cluster, SourceToConceptMap.cluster_id == Cluster.id)
        .where(Cluster.dataset_id == dataset_id)
    ).one()

    unmapped_clusters = total_clusters - mapped_clusters

    mapping_stats = MappingStatsResponse(
        total_clusters=total_clusters,
        mapped_clusters=mapped_clusters,
        unmapped_clusters=unmapped_clusters,
    )

    return DatasetOverviewResponse(
        dataset=dataset_response,
        stats=stats,
        clustering_stats=clustering_stats,
        mapping_stats=mapping_stats,
    )


@router.delete(
    "/{dataset_id}",
    response_model=MessageOutput,
    status_code=status.HTTP_200_OK,
    summary="Delete a dataset",
    description="Deletes a dataset and all its associated records (cascade delete)",
    response_description="Confirmation message that the dataset was deleted successfully",
)
def delete_dataset(
    background_tasks: BackgroundTasks,
    dataset_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    dataset = db.get(Dataset, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
        )

    verify_dataset_ownership(dataset, current_user.id)
    # remember the status so the background task can restore it if the
    # hard-delete fails, keeping the dataset recoverable.
    previous_status = dataset.status
    dataset.status = ProcessingStatus.DELETED
    db.commit()

    # start background deletion
    background_tasks.add_task(delete_dataset_background, dataset_id, previous_status)

    return MessageOutput(message="Dataset deletion started in the background")


def delete_dataset_background(
    dataset_id: int, previous_status: ProcessingStatus = ProcessingStatus.DONE
):
    with Session(engine) as db:
        try:
            dataset = db.get(Dataset, dataset_id)
            if dataset is None:
                logger.warning("Cannot find dataset %s to delete", dataset_id)
                return

            db.delete(dataset)
            db.commit()

            logger.info("Successfully deleted dataset %s", dataset_id)

        except Exception as e:
            db.rollback()
            logger.error(
                "Failed to hard-delete dataset %s: %s", dataset_id, e, exc_info=True
            )
            # The dataset was flagged DELETED before scheduling this task. Since
            # the hard-delete failed, restore the previous status (and surface
            # the error) so it is not silently stuck and the user can retry.
            try:
                dataset = db.get(Dataset, dataset_id)
                if dataset is not None:
                    dataset.status = previous_status
                    dataset.error_message = f"Deletion failed: {e}"
                    db.commit()
                    logger.info(
                        "Restored dataset %s to status %s after failed deletion",
                        dataset_id,
                        previous_status,
                    )
            except Exception as restore_error:
                db.rollback()
                logger.error(
                    "Failed to restore dataset %s after failed deletion: %s",
                    dataset_id,
                    restore_error,
                    exc_info=True,
                )


@router.get(
    "/{dataset_id}/download",
    response_class=StreamingResponse,
    status_code=status.HTTP_200_OK,
    summary="Download dataset",
    description="Downloads a dataset's records as a file",
    response_description="The file containing the dataset records",
)
def download_dataset(
    dataset_id: int,
    format: str = "csv",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    dataset = db.get(Dataset, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
        )
    verify_dataset_ownership(dataset, current_user.id)

    records = dataset.records
    if not records:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No records found for this dataset",
        )
    try:
        file_content, media_type = download_annotated_dataset(records, format)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    file_extension = "json" if format in {"json", "gliner"} else "csv"

    # Sanitize the dataset name before placing it in the Content-Disposition
    # header: strip quotes/control chars (header-injection guard) and replace
    # whitespace with underscores (same approach as omop_export.py).
    safe_name = re.sub(r'["\r\n\t]', "", dataset.name)
    safe_name = re.sub(r"\s+", "_", safe_name.strip())
    if not safe_name:
        safe_name = f"dataset_{dataset.id}"

    suffix_by_format = {
        "json": "records",
        "csv": "records",
        "gliner": "extracted_terms",
    }
    filename_parts = [safe_name]
    suffix = suffix_by_format.get(format)
    if suffix:
        filename_parts.append(suffix)
    filename = "_".join(filename_parts)

    return StreamingResponse(
        iter([file_content]),
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}.{file_extension}"'
        },
    )


# ================================================
# Dataset records routes
# ================================================


@router.post(
    "/{dataset_id}/records",
    response_model=RecordOutput,
    status_code=status.HTTP_201_CREATED,
    summary="Add a record to a dataset",
    description="Creates a new record and adds it to the specified dataset",
    response_description="The created record with its metadata",
)
def add_record(
    dataset_id: int,
    record: RecordCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    dataset = db.get(Dataset, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
        )
    verify_dataset_ownership(dataset, current_user.id)

    new_record = Record(
        patient_id=record.patient_id,
        seq_number=record.seq_number,
        visit_date=record.visit_date,
        text=record.text,
        dataset_id=dataset_id,
    )
    db.add(new_record)

    db.flush()
    regenerate_record_segments(db, new_record)
    link_dates_for_record(db, new_record, dataset)

    # Update dataset's last_modified timestamp
    dataset.last_modified = datetime.now(timezone.utc)

    db.commit()
    db.refresh(new_record)

    return RecordOutput(record=new_record)


@router.get(
    "/{dataset_id}/records",
    response_model=RecordsOutput,
    status_code=status.HTTP_200_OK,
    summary="List all records in a dataset",
    description="Retrieves all records belonging to a specific dataset with optional search and filter parameters",
    response_description="List of records in the dataset",
)
def get_records(
    dataset_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
    pagination: PaginationParams = Depends(),
    patient_id: Optional[str] = None,
    text: Optional[str] = None,
    reviewed: Optional[bool] = None,
):
    dataset = db.get(Dataset, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
        )
    verify_dataset_ownership(dataset, current_user.id)

    # Build base query
    query = select(Record).where(Record.dataset_id == dataset_id)
    count_query = (
        select(func.count()).select_from(Record).where(Record.dataset_id == dataset_id)
    )

    # Apply filters
    if patient_id:
        query = query.where(Record.patient_id.like(f"%{patient_id}%"))
        count_query = count_query.where(Record.patient_id.like(f"%{patient_id}%"))

    if text:
        query = query.where(Record.text.like(f"%{text}%"))
        count_query = count_query.where(Record.text.like(f"%{text}%"))

    if reviewed is not None:
        query = query.where(Record.reviewed == reviewed)
        count_query = count_query.where(Record.reviewed == reviewed)

    # Get total count with filters applied
    total = db.exec(count_query).one()

    # Get paginated records with filters
    records = db.exec(
        query.order_by(Record.id).offset(pagination.offset).limit(pagination.limit)
    ).all()

    # Get source term counts for these records
    record_ids = [r.id for r in records]
    term_counts = {}
    if record_ids:
        counts = db.exec(
            select(SourceTerm.record_id, func.count(SourceTerm.id))
            .where(SourceTerm.record_id.in_(record_ids))
            .group_by(SourceTerm.record_id)
        ).all()
        term_counts = {record_id: count for record_id, count in counts}

    # Build response with term counts
    records_with_counts = [
        RecordResponse(
            id=r.id,
            patient_id=r.patient_id,
            seq_number=r.seq_number,
            visit_date=r.visit_date,
            text=r.text,
            uploaded=r.uploaded,
            dataset_id=r.dataset_id,
            reviewed=r.reviewed,
            source_term_count=term_counts.get(r.id, 0),
        )
        for r in records
    ]

    return RecordsOutput(
        records=records_with_counts,
        pagination=create_pagination_metadata(
            total, pagination.limit, pagination.offset
        ),
    )


@router.get(
    "/{dataset_id}/records/{record_id}",
    response_model=RecordOutput,
    status_code=status.HTTP_200_OK,
    summary="Get a specific record",
    description="Retrieves a single record by its ID from a specific dataset",
    response_description="The requested record",
)
def get_record(
    dataset_id: int,
    record_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    dataset = db.get(Dataset, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
        )
    verify_dataset_ownership(dataset, current_user.id)

    statement = (
        select(Record)
        .where(Record.dataset_id == dataset_id)
        .where(Record.id == record_id)
    )
    record = db.exec(statement).one_or_none()

    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Record not found"
        )

    return RecordOutput(record=record)


@router.put(
    "/{dataset_id}/records/{record_id}",
    response_model=MessageOutput,
    status_code=status.HTTP_200_OK,
    summary="Update a record",
    description="Updates the text content of a specific record in a dataset",
    response_description="Confirmation message that the record was updated successfully",
)
def update_record(
    dataset_id: int,
    record_id: int,
    record: RecordCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    dataset = db.get(Dataset, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
        )
    verify_dataset_ownership(dataset, current_user.id)

    statement = (
        select(Record)
        .where(Record.dataset_id == dataset_id)
        .where(Record.id == record_id)
    )
    db_record = db.exec(statement).one_or_none()

    if db_record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Record not found"
        )

    db_record.text = record.text
    db_record.visit_date = record.visit_date

    db.flush()
    regenerate_record_segments(db, db_record)
    link_dates_for_record(db, db_record, dataset)

    # Update dataset's last_modified timestamp
    dataset.last_modified = datetime.now(timezone.utc)

    db.commit()

    return MessageOutput(message="Record updated successfully")


@router.delete(
    "/{dataset_id}/records/{record_id}",
    response_model=MessageOutput,
    status_code=status.HTTP_200_OK,
    summary="Delete a record",
    description="Deletes a specific record from a dataset",
    response_description="Confirmation message that the record was deleted successfully",
)
def delete_record(
    dataset_id: int,
    record_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    dataset = db.get(Dataset, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
        )
    verify_dataset_ownership(dataset, current_user.id)

    statement = (
        select(Record)
        .where(Record.dataset_id == dataset_id)
        .where(Record.id == record_id)
    )
    record = db.exec(statement).one_or_none()

    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Record not found"
        )

    db.delete(record)

    # Update dataset's last_modified timestamp
    dataset.last_modified = datetime.now(timezone.utc)

    db.commit()

    return MessageOutput(message="Record deleted successfully")


@router.put(
    "/{dataset_id}/records/{record_id}/review",
    response_model=MessageOutput,
    status_code=status.HTTP_200_OK,
    summary="Mark record as reviewed",
    description="Marks a specific record as reviewed or unreviewed",
    response_description="Confirmation message that the record review status was updated",
)
def review_record(
    dataset_id: int,
    record_id: int,
    reviewed: bool = True,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    dataset = db.get(Dataset, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
        )
    verify_dataset_ownership(dataset, current_user.id)

    statement = (
        select(Record)
        .where(Record.dataset_id == dataset_id)
        .where(Record.id == record_id)
    )
    db_record = db.exec(statement).one_or_none()

    if db_record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Record not found"
        )

    db_record.reviewed = reviewed

    # When a record is reviewed, clear automatically extracted flags on its terms
    if reviewed:
        auto_terms = db.exec(
            select(SourceTerm)
            .where(SourceTerm.record_id == record_id)
            .where(SourceTerm.automatically_extracted == True)
        ).all()
        for term in auto_terms:
            term.automatically_extracted = False

    db.commit()

    return MessageOutput(
        message=f"Record marked as {'reviewed' if reviewed else 'not reviewed'}"
    )


# ================================================
# Source terms routes (nested under records)
# ================================================


@router.post(
    "/{dataset_id}/records/{record_id}/source-terms",
    response_model=SourceTermOutput,
    status_code=status.HTTP_201_CREATED,
    summary="Create a source term",
    description="Creates a new source term associated with a specific record",
    response_description="The created source term",
)
def create_source_term_for_record(
    dataset_id: int,
    record_id: int,
    term: SourceTermCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    # Verify dataset ownership
    dataset = db.get(Dataset, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
        )
    verify_dataset_ownership(dataset, current_user.id)

    # Verify record exists and belongs to dataset
    statement = (
        select(Record)
        .where(Record.dataset_id == dataset_id)
        .where(Record.id == record_id)
    )
    record = db.exec(statement).one_or_none()

    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Record not found"
        )

    source_term = SourceTerm(
        record_id=record_id,
        value=term.value,
        label=term.label,
        start_position=term.start_position,
        end_position=term.end_position,
    )
    db.add(source_term)
    db.flush()
    link_dates_for_record(db, record, dataset)
    db.commit()
    db.refresh(source_term)
    return SourceTermOutput(source_term=source_term)


@router.get(
    "/{dataset_id}/records/{record_id}/source-terms",
    response_model=SourceTermsOutput,
    status_code=status.HTTP_200_OK,
    summary="List all source terms for a record",
    description="Retrieves all source terms associated with a specific record",
    response_description="List of source terms in the record",
)
def get_source_terms_of_record(
    dataset_id: int,
    record_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
    pagination: PaginationParams = Depends(),
):
    # Verify dataset ownership
    dataset = db.get(Dataset, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
        )
    verify_dataset_ownership(dataset, current_user.id)

    # Verify record exists and belongs to dataset
    statement = (
        select(Record)
        .where(Record.dataset_id == dataset_id)
        .where(Record.id == record_id)
    )
    record = db.exec(statement).one_or_none()

    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Record not found"
        )

    # Get total count
    total = db.exec(
        select(func.count())
        .select_from(SourceTerm)
        .where(SourceTerm.record_id == record_id)
    ).one()

    # Get paginated source terms
    source_terms = db.exec(
        select(SourceTerm)
        .where(SourceTerm.record_id == record_id)
        .order_by(SourceTerm.id)
        .offset(pagination.offset)
        .limit(pagination.limit)
    ).all()

    # Load all links for these terms (both directions)
    term_ids = [t.id for t in source_terms]
    all_links = db.exec(
        select(SourceTermLink).where(
            (SourceTermLink.from_term_id.in_(term_ids))
            | (SourceTermLink.to_term_id.in_(term_ids))
        )
    ).all()

    # Build a map of term_id -> list of SourceTermLinkResponse
    term_map = {t.id: t for t in source_terms}
    links_by_term: dict[int, list] = {t.id: [] for t in source_terms}
    for link in all_links:
        from_t = term_map.get(link.from_term_id)
        to_t = term_map.get(link.to_term_id)
        if from_t is None or to_t is None:
            continue
        link_resp = SourceTermLinkResponse(
            id=link.id,
            from_term_id=link.from_term_id,
            to_term_id=link.to_term_id,
            from_term_value=from_t.value,
            to_term_value=to_t.value,
            from_term_label=from_t.label,
            to_term_label=to_t.label,
        )
        if link.from_term_id in links_by_term:
            links_by_term[link.from_term_id].append(link_resp)
        if link.to_term_id in links_by_term:
            links_by_term[link.to_term_id].append(link_resp)

    source_term_responses = [
        SourceTermResponse(
            id=t.id,
            value=t.value,
            label=t.label,
            start_position=t.start_position,
            end_position=t.end_position,
            score=t.score,
            automatically_extracted=t.automatically_extracted,
            record_id=t.record_id,
            linked_visit_date=t.linked_visit_date,
            manual_linked_visit_date=t.manual_linked_visit_date,
            linked_date_term_id=t.linked_date_term_id,
            cluster_id=t.cluster_id,
            links=links_by_term.get(t.id, []),
        )
        for t in source_terms
    ]

    return SourceTermsOutput(
        source_terms=source_term_responses,
        pagination=create_pagination_metadata(
            total, pagination.limit, pagination.offset
        ),
    )


# ================================================
# Clusters routes (nested under datasets)
# ================================================


@router.get("/{dataset_id}/clusters", response_model=ClustersStatisticsOutput)
def get_clusters_of_dataset(
    dataset_id: int,
    label: Union[str, None] = None,
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """
    Get structured cluster data for a dataset with filtering by label.
    Returns clusters with aggregated stats + unclustered terms list.
    """
    # Verify dataset exists and user owns it
    dataset = db.get(Dataset, dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    verify_dataset_ownership(dataset, current_user.id)

    # Build cluster query
    cluster_query = select(Cluster).where(Cluster.dataset_id == dataset_id)
    if label:
        cluster_query = cluster_query.where(Cluster.label == label)

    clusters = db.exec(cluster_query).all()

    # Build response with aggregated data
    cluster_responses = []
    for cluster in clusters:
        # Get all source terms for this cluster
        terms_dict = defaultdict(lambda: {"frequency": 0, "record_ids": set()})

        for term in cluster.source_terms:
            terms_dict[term.value]["frequency"] += 1
            terms_dict[term.value]["record_ids"].add(term.record_id)
            terms_dict[term.value]["term_id"] = term.id

        clustered_terms = [
            ClusteredTerm(
                term_id=data["term_id"],
                text=text,
                frequency=data["frequency"],
                n_records=len(data["record_ids"]),
                record_ids=list(data["record_ids"]),
            )
            for text, data in terms_dict.items()
        ]

        total_occurrences = sum(t.frequency for t in clustered_terms)
        unique_records = len(
            set(rec_id for t in clustered_terms for rec_id in t.record_ids)
        )

        cluster_responses.append(
            ClusterResponse(
                id=cluster.id,
                dataset_id=cluster.dataset_id,
                label=cluster.label,
                title=cluster.title,
                total_terms=len(clustered_terms),
                total_occurrences=total_occurrences,
                unique_records=unique_records,
                terms=clustered_terms,
            )
        )

    # Get unclustered terms for this dataset/label
    unclustered_query = (
        select(SourceTerm)
        .join(Record)
        .where(Record.dataset_id == dataset_id)
        .where(Record.reviewed == True)
        .where(SourceTerm.cluster_id == None)
    )
    if label:
        unclustered_query = unclustered_query.where(SourceTerm.label == label)

    unclustered_source_terms = db.exec(unclustered_query).all()

    # Aggregate unclustered terms by value
    unclustered_dict = defaultdict(lambda: {"frequency": 0, "record_ids": set()})
    for term in unclustered_source_terms:
        unclustered_dict[term.value]["frequency"] += 1
        unclustered_dict[term.value]["record_ids"].add(term.record_id)
        unclustered_dict[term.value]["term_id"] = term.id

    unclustered_terms = [
        ClusteredTerm(
            term_id=data["term_id"],
            text=text,
            frequency=data["frequency"],
            n_records=len(data["record_ids"]),
            record_ids=list(data["record_ids"]),
        )
        for text, data in unclustered_dict.items()
    ]

    # Get all labels in dataset
    all_labels = dataset.labels

    # Calculate total terms
    total_number_terms = sum(cr.total_terms for cr in cluster_responses) + len(
        unclustered_terms
    )

    # label_reviewed: True if a label is selected and ALL its clusters are reviewed
    label_reviewed = (
        bool(label) and len(clusters) > 0 and all(c.reviewed for c in clusters)
    )

    return ClustersStatisticsOutput(
        clusters=cluster_responses,
        unclustered_terms=unclustered_terms,
        total_number_terms=total_number_terms,
        labels=all_labels,
        label_reviewed=label_reviewed,
    )


@router.post(
    "/{dataset_id}/clusters/review-label",
    response_model=MessageOutput,
)
def review_label(
    dataset_id: int,
    body: ClusterReviewLabelRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """Mark all clusters for a given label as reviewed."""
    dataset = db.get(Dataset, dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    verify_dataset_ownership(dataset, current_user.id)

    clusters = db.exec(
        select(Cluster)
        .where(Cluster.dataset_id == dataset_id)
        .where(Cluster.label == body.label)
    ).all()

    for cluster in clusters:
        cluster.reviewed = True
        db.add(cluster)

    db.commit()
    return MessageOutput(message=f"Marked {len(clusters)} clusters as reviewed")


@router.post(
    "/{dataset_id}/clusters/unreview-label",
    response_model=MessageOutput,
)
def unreview_label(
    dataset_id: int,
    body: ClusterReviewLabelRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """Unmark all clusters for a given label as reviewed."""
    dataset = db.get(Dataset, dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    verify_dataset_ownership(dataset, current_user.id)

    clusters = db.exec(
        select(Cluster)
        .where(Cluster.dataset_id == dataset_id)
        .where(Cluster.label == body.label)
    ).all()

    for cluster in clusters:
        cluster.reviewed = False
        db.add(cluster)

    db.commit()
    return MessageOutput(message=f"Unmarked {len(clusters)} clusters as reviewed")


def _normalize_term(text: str) -> str:
    """Normalize term text: lowercase, unify separators, remove punctuation, collapse spaces."""
    s = (text or "").lower().strip()
    s = s.replace("-", " ")
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _levenshtein(a: str, b: str, max_dist: int = 1) -> int:
    if a == b:
        return 0
    if abs(len(a) - len(b)) > max_dist:
        return max_dist + 1
    if len(a) > len(b):
        a, b = b, a

    prev = list(range(len(a) + 1))
    for i, cb in enumerate(b, start=1):
        cur = [i]
        # early-stop lower bound in the row
        row_min = cur[0]
        for j, ca in enumerate(a, start=1):
            cost = 0 if ca == cb else 1
            cur_val = min(
                prev[j] + 1,  # deletion
                cur[j - 1] + 1,  # insertion
                prev[j - 1] + cost,  # substitution
            )
            cur.append(cur_val)
            row_min = min(row_min, cur_val)

        if row_min > max_dist:
            return max_dist + 1
        prev = cur
    return prev[-1]


def _merge_labels_by_spelling(
    labels_arr: List[int], texts: List[str], max_typos: int = 1
) -> List[int]:
    # Build: cluster_id -> list of normalized base forms of its members
    cluster_to_terms = defaultdict(list)
    for text, cid in zip(texts, labels_arr):
        if cid == -1:
            continue
        norm = _normalize_term(text)
        cluster_to_terms[int(cid)].append(norm)

    if len(cluster_to_terms) <= 1:
        return (
            labels_arr.tolist() if hasattr(labels_arr, "tolist") else list(labels_arr)
        )

    # Pick a representative base key for each cluster (most frequent base form)
    rep = {}
    for cid, bases in cluster_to_terms.items():
        rep[cid] = max(set(bases), key=bases.count)

    # Merge clusters if their representative keys are very close
    ids = list(rep.keys())
    parent = {cid: cid for cid in ids}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            a, b = ids[i], ids[j]
            da = rep[a]
            db = rep[b]

            # Quick merge if same base
            if da == db:
                union(a, b)
                continue

            # Allow up to `max_typos` typos
            if _levenshtein(da, db, max_dist=max_typos) <= max_typos:
                union(a, b)

    # remap labels to merged roots
    remap = {cid: find(cid) for cid in ids}
    merged = []
    for cid in labels_arr:
        if cid == -1:
            merged.append(-1)
        else:
            merged.append(remap[int(cid)])
    return merged


def _to_list_matrix(embeddings) -> List[List[float]]:
    """
    Convert embeddings to list of listd regardless of whether they come as:
    1. list of lists
    2. numpy array
    3. something with .tolist()
    or one option?
    """
    if hasattr(embeddings, "tolist"):
        return embeddings.tolist()
    return embeddings


def _merge_labels_by_centroid_similarity(
    labels_arr: List[int],
    embeddings,
    threshold: float = 0.8,
) -> List[int]:
    """
    Merge clusters if cosine similarity between their centroids >= threshold.
    Noise (-1) is ignored.
    Should we use numpy insted?
    """
    labels = labels_arr.tolist() if hasattr(labels_arr, "tolist") else list(labels_arr)
    E = _to_list_matrix(embeddings)

    # cluster_id -> list of vectors (members)
    cluster_vecs = defaultdict(list)
    for idx, cid in enumerate(labels):
        if cid == -1:
            continue
        cluster_vecs[int(cid)].append(E[idx])

    cluster_ids = list(cluster_vecs.keys())
    if len(cluster_ids) <= 1:
        return labels

    # compute centroid for each cluster
    centroids = {cid: _compute_centroid(cluster_vecs[cid]) for cid in cluster_ids}

    # union-find for merging cluster IDs
    parent = {cid: cid for cid in cluster_ids}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    # compare all pairs (ok for typical number of clusters per label)
    for i in range(len(cluster_ids)):
        for j in range(i + 1, len(cluster_ids)):
            a = cluster_ids[i]
            b = cluster_ids[j]
            sim = _cosine_similarity(centroids[a], centroids[b])
            if sim >= threshold:
                union(a, b)

    # remap label ids to merged roots
    remap = {cid: find(cid) for cid in cluster_ids}
    merged = []
    for cid in labels:
        if cid == -1:
            merged.append(-1)
        else:
            merged.append(remap[int(cid)])
    return merged


def _cluster_dataset_label(db: Session, dataset_id: int, label: str) -> tuple[int, int]:
    """Rebuild clusters for a single ``(dataset_id, label)``.

    Shared by the per-label endpoint and the "cluster all labels" batch worker.
    Selects the reviewed-record source terms for the label, clusters them
    (dates → exact key, measures → normalized key, else embeddings + HDBSCAN),
    then destructively replaces the label's existing clusters with the result.

    Returns ``(clusters_created, terms_count)``. ``(0, 0)`` when the label has no
    source terms to cluster (caller treats this as a no-op, not an error). Does
    NOT perform ownership/existence checks — callers are responsible for those.
    """
    source_terms = db.exec(
        select(SourceTerm)
        .join(Record)
        .where(Record.dataset_id == dataset_id)
        .where(Record.reviewed == True)  # noqa: E712
        .where(SourceTerm.label == label)
    ).all()

    if not source_terms:
        return (0, 0)

    raw_texts = [st.value for st in source_terms]
    if not raw_texts:
        return (0, 0)

    # 1) Decide value type for this label by majority vote
    types = []
    date_keys = []
    measure_keys = []

    for t in raw_texts:
        tp = detect_value_type(t)

        dt_key = normalize_date_to_key(t) if tp == "date" else None
        ms_key = normalize_measure_to_key(t) if tp == "measure" else None

        if tp == "date" and dt_key is None:
            tp = "text"
        if tp == "measure" and ms_key is None:
            tp = "text"

        types.append(tp)
        date_keys.append(dt_key)
        measure_keys.append(ms_key)

    type_counts = Counter(types)
    major_type = type_counts.most_common(1)[0][0]

    # 2) If it's dates: cluster by exact canonical key
    if major_type == "date":
        key_to_cluster = {}
        labels_arr = []
        next_id = 0

        for key in date_keys:
            if key is None:
                labels_arr.append(-1)  # unclustered if can't parse
                continue
            if key not in key_to_cluster:
                key_to_cluster[key] = next_id
                next_id += 1
            labels_arr.append(key_to_cluster[key])

        # For title picking later we still need texts (original)
        texts = raw_texts

    # 3) If it's measures: normalize -> cluster by exact match of normalized key
    elif major_type == "measure":
        key_to_cluster = {}
        labels_arr = []
        next_id = 0

        for key in measure_keys:
            if key is None:
                labels_arr.append(-1)
                continue
            if key not in key_to_cluster:
                key_to_cluster[key] = next_id
                next_id += 1
            labels_arr.append(key_to_cluster[key])

        texts = raw_texts

    # 4) Otherwise: default pipeline (embeddings + HDBSCAN + merges)
    else:
        texts = [_normalize_term(t) for t in raw_texts]

        embedding_model = model_registry.get_model("embedding_sentence")
        embeddings = embedding_model.embed(texts)

        HDBSCAN_PARAMS = {
            "min_cluster_size": 2,
            "min_samples": None,
            "metric": "euclidean",
            "cluster_selection_method": "eom",
        }

        if len(texts) < HDBSCAN_PARAMS["min_cluster_size"]:
            # Too few samples for HDBSCAN — treat all as noise so the
            # noise-grouping block below creates one cluster per term.
            labels_arr = [-1] * len(texts)
        else:
            clusterer = HDBSCAN(**HDBSCAN_PARAMS)
            labels_arr = clusterer.fit_predict(embeddings)

            labels_arr = _merge_labels_by_spelling(
                labels_arr.tolist() if hasattr(labels_arr, "tolist") else labels_arr,
                texts,
                max_typos=1,
            )

            labels_arr = _merge_labels_by_centroid_similarity(
                labels_arr, embeddings, threshold=0.8
            )
            labels_arr = [int(x) for x in labels_arr]

    # Remove existing clusters for this dataset/label
    # TODO: This might be a bit dangerous if the user is not careful
    old_clusters = db.exec(
        select(Cluster)
        .where(Cluster.dataset_id == dataset_id)
        .where(Cluster.label == label)
    ).all()

    for c in old_clusters:
        db.delete(c)
    db.commit()

    # Create new clusters
    cluster_terms = defaultdict(list)
    noise_terms = []

    for st, cid in zip(source_terms, labels_arr):
        if cid == -1:
            noise_terms.append(st)
        else:
            cluster_terms[cid].append(st)

    created_by_title_norm = {}

    for cid, terms in cluster_terms.items():
        counter = Counter(st.value for st in terms)
        title = counter.most_common(1)[0][0]
        title_norm = _normalize_term(title)

        if title_norm in created_by_title_norm:
            cluster_obj = created_by_title_norm[title_norm]
        else:
            cluster_obj = Cluster(dataset_id=dataset_id, label=label, title=title)
            db.add(cluster_obj)
            db.commit()
            db.refresh(cluster_obj)
            created_by_title_norm[title_norm] = cluster_obj

        for st in terms:
            st.cluster_id = cluster_obj.id
            db.add(st)

    noise_groups = defaultdict(list)
    for st in noise_terms:
        noise_groups[_normalize_term(st.value)].append(st)

    for norm_key, terms in noise_groups.items():
        counter = Counter(st.value for st in terms)
        title = counter.most_common(1)[0][0]
        title_norm = _normalize_term(title)

        if title_norm in created_by_title_norm:
            cluster_obj = created_by_title_norm[title_norm]
        else:
            cluster_obj = Cluster(dataset_id=dataset_id, label=label, title=title)
            db.add(cluster_obj)
            db.commit()
            db.refresh(cluster_obj)
            created_by_title_norm[title_norm] = cluster_obj

        for st in terms:
            st.cluster_id = cluster_obj.id
            db.add(st)

    db.commit()

    return (len(created_by_title_norm), len(source_terms))


@router.post("/{dataset_id}/clusters/create", response_model=MessageOutput)
def create_clusters_for_dataset(
    dataset_id: int,
    label: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    dataset = db.get(Dataset, dataset_id)
    if not dataset:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
        )
    verify_dataset_ownership(dataset, current_user.id)

    _clusters_created, terms_count = _cluster_dataset_label(db, dataset_id, label)
    if terms_count == 0:
        return MessageOutput(message="No source terms for this label in dataset")

    return MessageOutput(message="Clusters rebuilt and saved to database.")


def _cluster_job_status(job: ClusterJob) -> ClusterJobStatusResponse:
    return ClusterJobStatusResponse(
        job_id=job.id,
        dataset_id=job.dataset_id,
        total=job.total,
        completed=job.completed,
        status=job.status,
        clustered_labels=job.clustered_labels,
        skipped_labels=job.skipped_labels,
        error_message=job.error_message,
    )


def _label_has_reviewed_cluster(db: Session, dataset_id: int, label: str) -> bool:
    """A label is "reviewed" (→ skip re-clustering) if any of its clusters is
    marked reviewed. Re-clustering wipes the label's clusters and cascades to
    delete their concept mappings, so reviewed labels must be preserved."""
    return (
        db.exec(
            select(Cluster.id)
            .where(Cluster.dataset_id == dataset_id)
            .where(Cluster.label == label)
            .where(Cluster.reviewed == True)  # noqa: E712
        ).first()
        is not None
    )


@router.post(
    "/{dataset_id}/clusters/cluster-all", response_model=ClusterJobStartResponse
)
def cluster_all_labels(
    dataset_id: int,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """Kick off clustering for every label in the dataset.

    Returns immediately with a job id; progress (in labels) can be polled via the
    status endpoint. Labels with a reviewed cluster are skipped, not re-clustered.
    """
    dataset = db.get(Dataset, dataset_id)
    if not dataset:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
        )
    verify_dataset_ownership(dataset, current_user.id)

    active_job = db.exec(
        select(ClusterJob)
        .where(ClusterJob.dataset_id == dataset_id)
        .where((ClusterJob.status == "pending") | (ClusterJob.status == "running"))
    ).first()
    if active_job is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A clustering job is already running for this dataset",
        )

    # Only one job is the "currently used" one for the dataset.
    currently_used_job = db.exec(
        select(ClusterJob)
        .where(ClusterJob.currently_used == True)  # noqa: E712
        .where(ClusterJob.dataset_id == dataset_id)
        .order_by(ClusterJob.created_at.desc())
    ).first()
    if currently_used_job is not None:
        currently_used_job.currently_used = False
        db.add(currently_used_job)
        db.commit()

    labels = dataset.labels or []
    job = ClusterJob(
        dataset_id=dataset_id,
        total=len(labels),
        completed=0,
        status="pending",
        currently_used=True,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    if not labels:
        job.status = "completed"
        job.updated_at = datetime.now(timezone.utc)
        db.add(job)
        db.commit()
        return ClusterJobStartResponse(
            job_id=job.id,
            dataset_id=dataset_id,
            total=job.total,
            status=job.status,
        )

    background_tasks.add_task(
        run_cluster_all_job,
        job_id=job.id,
        dataset_id=dataset_id,
    )

    return ClusterJobStartResponse(
        job_id=job.id,
        dataset_id=dataset_id,
        total=job.total,
        status=job.status,
    )


@router.get(
    "/{dataset_id}/clusters/cluster-all/active",
    response_model=Optional[ClusterJobStatusResponse],
)
def get_active_cluster_job(
    dataset_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """Return the latest pending/running cluster-all job for the dataset, or null."""
    dataset = db.get(Dataset, dataset_id)
    if not dataset:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
        )
    verify_dataset_ownership(dataset, current_user.id)

    job = db.exec(
        select(ClusterJob)
        .where(ClusterJob.dataset_id == dataset_id)
        .where((ClusterJob.status == "pending") | (ClusterJob.status == "running"))
        .order_by(ClusterJob.created_at.desc())
    ).first()

    if job is None:
        return None

    return _cluster_job_status(job)


@router.get(
    "/{dataset_id}/clusters/cluster-all/{job_id}/status",
    response_model=ClusterJobStatusResponse,
)
def get_cluster_job_status(
    dataset_id: int,
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """Return progress for a dataset cluster-all job."""
    dataset = db.get(Dataset, dataset_id)
    if not dataset:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
        )
    verify_dataset_ownership(dataset, current_user.id)

    job = db.get(ClusterJob, job_id)
    if job is None or job.dataset_id != dataset_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Clustering job not found for this dataset",
        )

    return _cluster_job_status(job)


@router.post(
    "/{dataset_id}/clusters/cluster-all/{job_id}/cancel",
    response_model=MessageOutput,
)
def cancel_cluster_job(
    dataset_id: int,
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """Request cancellation of a cluster-all job. Already-clustered labels remain."""
    dataset = db.get(Dataset, dataset_id)
    if not dataset:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
        )
    verify_dataset_ownership(dataset, current_user.id)

    job = db.get(ClusterJob, job_id)
    if job is None or job.dataset_id != dataset_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Clustering job not found for this dataset",
        )

    if job.status in {"completed", "failed", "cancelled"}:
        return MessageOutput(message=f"Job already {job.status}")

    job.status = "cancelled"
    job.updated_at = datetime.now(timezone.utc)
    db.add(job)
    db.commit()

    return MessageOutput(message="Cancellation requested")


def run_cluster_all_job(job_id: int, dataset_id: int):
    """Background task that clusters every label in the dataset.

    Skips any label that already has a reviewed cluster (re-clustering is
    destructive) and records the clustered/skipped labels on the job so the UI
    can report them. Progress is measured in labels.
    """
    with Session(engine) as session:
        job = session.get(ClusterJob, job_id)
        if job is None:
            return

        dataset = session.get(Dataset, dataset_id)
        if dataset is None:
            job.status = "failed"
            job.error_message = "Dataset not found"
            job.updated_at = datetime.now(timezone.utc)
            session.add(job)
            session.commit()
            return

        if job.status == "cancelled":
            return

        job.status = "running"
        job.updated_at = datetime.now(timezone.utc)
        session.add(job)
        session.commit()

        labels = dataset.labels or []
        clustered: List[str] = []
        skipped: List[str] = []

        for label in labels:
            session.refresh(job)
            if job.status == "cancelled":
                job.updated_at = datetime.now(timezone.utc)
                session.add(job)
                session.commit()
                return

            try:
                if _label_has_reviewed_cluster(session, dataset_id, label):
                    skipped.append(label)
                else:
                    _cluster_dataset_label(session, dataset_id, label)
                    clustered.append(label)
            except Exception as exc:  # noqa: BLE001 — surface any failure on the job
                job.status = "failed"
                job.error_message = f"Failed to cluster label '{label}': {exc}"
                job.updated_at = datetime.now(timezone.utc)
                session.add(job)
                session.commit()
                return

            job.completed += 1
            job.clustered_labels = list(clustered)
            job.skipped_labels = list(skipped)
            job.updated_at = datetime.now(timezone.utc)
            session.add(job)
            session.commit()

        job.status = "completed"
        job.updated_at = datetime.now(timezone.utc)
        session.add(job)
        session.commit()


DATE_SEPARATORS_RE = re.compile(r"[.\-/]")

MEASURE_RE = re.compile(
    r"^\s*\d+(?:\s*/\s*\d+)?(?:[.,]\d+)?\s*(mg|ml|g|mcg|µg|kg|iu|%)\s*$",
    re.IGNORECASE,
)


@router.post("/{dataset_id}/clusters", response_model=ClusterResponse)
def create_cluster_endpoint(
    dataset_id: int,
    data: ClusterCreate,
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """
    Create new empty cluster manually.
    Allows manual cluster creation during editing workflow.
    """
    # Verify dataset exists and user owns it
    dataset = db.get(Dataset, dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    verify_dataset_ownership(dataset, current_user.id)

    # Create new cluster
    new_cluster = Cluster(
        dataset_id=dataset_id,
        label=data.label,
        title=data.title,
    )
    db.add(new_cluster)
    db.commit()
    db.refresh(new_cluster)

    # Return as ClusterResponse
    return ClusterResponse(
        id=new_cluster.id,
        dataset_id=new_cluster.dataset_id,
        label=new_cluster.label,
        title=new_cluster.title,
        total_terms=0,
        total_occurrences=0,
        unique_records=0,
        terms=[],
    )


@router.post("/{dataset_id}/clusters/merge", response_model=MessageOutput)
def merge_clusters_endpoint(
    dataset_id: int,
    data: ClusterMerge,
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """
    Merge multiple clusters into a single new cluster.
    Combines all terms from source clusters and deletes old clusters.
    """
    # Verify dataset exists and user owns it
    dataset = db.get(Dataset, dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    verify_dataset_ownership(dataset, current_user.id)

    # Verify all clusters exist and belong to this dataset
    clusters_to_merge = []
    for cluster_id in data.cluster_ids:
        cluster = db.get(Cluster, cluster_id)
        if not cluster:
            raise HTTPException(404, f"Cluster {cluster_id} not found")
        if cluster.dataset_id != dataset_id:
            raise HTTPException(
                400, f"Cluster {cluster_id} does not belong to dataset {dataset_id}"
            )
        clusters_to_merge.append(cluster)

    # All clusters should have the same label
    labels = set(c.label for c in clusters_to_merge)
    if len(labels) > 1:
        raise HTTPException(400, "All clusters must have the same label")

    label = clusters_to_merge[0].label

    # Create new merged cluster
    merged_cluster = Cluster(
        dataset_id=dataset_id,
        label=label,
        title=data.new_title,
    )
    db.add(merged_cluster)
    db.commit()
    db.refresh(merged_cluster)

    # Collect all term IDs first to avoid issues with ondelete="SET NULL"
    # when deleting old clusters
    cluster_ids_to_merge = [c.id for c in clusters_to_merge]
    terms_to_move = db.exec(
        select(SourceTerm).where(SourceTerm.cluster_id.in_(cluster_ids_to_merge))
    ).all()

    # Update all terms to point to the new merged cluster
    total_terms_moved = len(terms_to_move)
    for term in terms_to_move:
        term.cluster_id = merged_cluster.id
        db.add(term)

    # Commit the term updates first
    db.commit()

    # Now delete old clusters (terms already moved, so ondelete won't affect them)
    for old_cluster in clusters_to_merge:
        db.delete(old_cluster)

    db.commit()

    return MessageOutput(
        message=f"Merged {len(data.cluster_ids)} clusters into '{data.new_title}' (moved {total_terms_moved} terms)"
    )


@router.delete(
    "/{dataset_id}/source-terms",
    response_model=MessageOutput,
    status_code=status.HTTP_200_OK,
    summary="Delete extracted source terms in a dataset",
    description="Removes all automatically extracted source terms for the dataset so extraction can be rerun cleanly",
)
def delete_extracted_source_terms(
    dataset_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    # Verify dataset ownership
    dataset = db.get(Dataset, dataset_id)
    if dataset is None:
        raise HTTPException(status_code=404, detail="Dataset not found")
    verify_dataset_ownership(dataset, current_user.id)

    # Delete only automatically extracted terms for records in this dataset
    terms = db.exec(
        select(SourceTerm)
        .join(Record)
        .where(Record.dataset_id == dataset_id)
        .where(SourceTerm.automatically_extracted == True)  # noqa: E712
    ).all()

    for term in terms:
        db.delete(term)

    db.commit()
    return MessageOutput(
        message=f"Deleted {len(terms)} automatically extracted source terms"
    )


@router.get(
    "/{dataset_id}/clusters/download",
    response_class=StreamingResponse,
    status_code=status.HTTP_200_OK,
    summary="Download clusters JSON",
    description="Exports clusters (optionally filtered by label) as a JSON attachment",
)
def download_clusters_json(
    dataset_id: int,
    label: Optional[str] = None,
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    dataset = db.get(Dataset, dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    verify_dataset_ownership(dataset, current_user.id)

    cluster_stmt = select(Cluster).where(Cluster.dataset_id == dataset_id)
    if label:
        cluster_stmt = cluster_stmt.where(Cluster.label == label)
    clusters = db.exec(cluster_stmt.order_by(Cluster.title)).all()
    if not clusters:
        raise HTTPException(
            status_code=404, detail="No clusters found for this dataset"
        )

    cluster_ids = [c.id for c in clusters]
    term_rows = []
    if cluster_ids:
        term_rows = db.exec(
            select(SourceTerm.cluster_id, SourceTerm.value).where(
                SourceTerm.cluster_id.in_(cluster_ids)
            )
        ).all()

    content, filename = build_clusters_download_json(
        dataset.name,
        clusters,
        term_rows,
    )
    return StreamingResponse(
        iter([content]),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
