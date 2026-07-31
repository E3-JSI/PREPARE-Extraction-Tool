import io
import csv
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    status,
    File,
    UploadFile,
)
from fastapi.responses import StreamingResponse
from sqlmodel import Session, select

from app.core.database import engine, get_session
from app.models_db import (
    Dataset,
    Cluster,
    Concept,
    MappingJob,
    SourceToConceptMap,
    User,
)
from app.library.concept_indexer import indexer
from app.library.omop_export import build_omop_cdm_zip
from app.routes.v1.auth import get_current_user
from app.schemas import (
    MessageOutput,
    ClusterMappingResponse,
    ClusterMappingsOutput,
    ConceptSearchResult,
    ConceptSearchResults,
    AutoMapRequest,
    MapClusterRequest,
    AutoMapAllRequest,
    MappingJobStartResponse,
    MappingJobStatusResponse,
    ConceptHierarchy,
)

# ================================================
# Route definitions
# ================================================

router = APIRouter()


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
# Mapping routes
# ================================================


@router.get(
    "/{dataset_id}/mappings",
    response_model=ClusterMappingsOutput,
    status_code=status.HTTP_200_OK,
    summary="Get all cluster mappings for a dataset",
    description="Returns all clusters with their mapping status and concept information",
)
def get_dataset_mappings(
    dataset_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
    label: Optional[str] = None,
):
    """Get all cluster mappings for a dataset."""
    # Verify dataset ownership
    dataset = db.get(Dataset, dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    verify_dataset_ownership(dataset, current_user.id)

    # Build cluster query - only include reviewed clusters
    cluster_query = select(Cluster).where(Cluster.dataset_id == dataset_id)
    cluster_query = cluster_query.where(Cluster.reviewed == True)
    if label:
        cluster_query = cluster_query.where(Cluster.label == label)

    clusters = db.exec(cluster_query).all()

    mappings = []
    mapped_count = 0
    approved_count = 0

    for cluster in clusters:
        # Count distinct term values vs. total occurrences, consistent with the
        # clusters overview in datasets.py: terms are collapsed by `value`, so
        # term_count is the number of distinct values while total_occurrences is
        # the raw number of extracted source-term rows.
        term_count = len({term.value for term in cluster.source_terms})
        total_occurrences = len(cluster.source_terms)

        # Check if cluster has a mapping
        mapping_entry = None
        if cluster.mapping:
            mapping_entry = cluster.mapping[0]  # Get first mapping

        if mapping_entry:
            concept = mapping_entry.concept
            vocabulary = concept.vocabulary if concept else None

            mapping = ClusterMappingResponse(
                cluster_id=cluster.id,
                cluster_title=cluster.title,
                cluster_label=cluster.label,
                cluster_term_count=term_count,
                cluster_total_occurrences=total_occurrences,
                concept_id=concept.id if concept else None,
                concept_term_id=concept.vocab_term_id if concept else None,
                concept_term_name=concept.vocab_term_name if concept else None,
                concept_code=concept.concept_code if concept else None,
                concept_domain=concept.domain_id if concept else None,
                concept_class=concept.concept_class_id if concept else None,
                vocabulary_id=vocabulary.id if vocabulary else None,
                vocabulary_name=vocabulary.name if vocabulary else None,
                status=mapping_entry.status,
                comment=mapping_entry.comment,
                created_at=mapping_entry.created_at,
                updated_at=mapping_entry.updated_at,
            )
            mapped_count += 1
            if mapping_entry.status == "approved":
                approved_count += 1
        else:
            mapping = ClusterMappingResponse(
                cluster_id=cluster.id,
                cluster_title=cluster.title,
                cluster_label=cluster.label,
                cluster_term_count=term_count,
                cluster_total_occurrences=total_occurrences,
                status="unmapped",
            )

        mappings.append(mapping)

    return ClusterMappingsOutput(
        mappings=mappings,
        total_clusters=len(clusters),
        mapped_count=mapped_count,
        unmapped_count=len(clusters) - mapped_count,
        approved_count=approved_count,
    )


@router.post(
    "/{dataset_id}/clusters/{cluster_id}/auto-map",
    response_model=ConceptSearchResults,
    status_code=status.HTTP_200_OK,
    summary="Auto-map a cluster to concepts",
    description="Searches for best matching concepts using cluster title and terms",
)
def auto_map_cluster(
    dataset_id: int,
    cluster_id: int,
    request: AutoMapRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """Auto-map a cluster by searching for matching concepts."""
    # Verify dataset ownership
    dataset = db.get(Dataset, dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    verify_dataset_ownership(dataset, current_user.id)

    # Get cluster
    cluster = db.get(Cluster, cluster_id)
    if not cluster or cluster.dataset_id != dataset_id:
        raise HTTPException(status_code=404, detail="Cluster not found")

    if not cluster.reviewed:
        raise HTTPException(
            status_code=400,
            detail="Cluster must be reviewed before mapping",
        )

    # Build search query from cluster title and optionally top terms
    search_text = cluster.title

    if request.use_cluster_terms and cluster.source_terms:
        # Get top 5 most frequent terms
        term_freq = defaultdict(int)
        for term in cluster.source_terms:
            term_freq[term.value] += 1

        top_terms = sorted(term_freq.items(), key=lambda x: x[1], reverse=True)[:5]
        search_text += " " + " ".join([term for term, _ in top_terms])

    # Search using Elasticsearch - choose method based on search_type
    if request.search_type == "vector":
        es_results, _ = indexer.search_concepts_vector(
            query_text=search_text,
            vocab_ids=request.vocabulary_ids,
            limit=10,
            domain_id=request.domain_id,
            concept_class_id=request.concept_class_id,
            standard_concept=request.standard_concept,
        )
    else:
        es_results, _ = indexer.search_concepts(
            query_text=search_text,
            vocab_ids=request.vocabulary_ids,
            limit=10,
            domain_id=request.domain_id,
            concept_class_id=request.concept_class_id,
            standard_concept=request.standard_concept,
        )

    # Get concept details from database
    results = []
    for es_result in es_results:
        concept = db.get(Concept, es_result["concept_id"])
        if not concept:
            continue

        vocabulary = concept.vocabulary
        results.append(
            ConceptSearchResult(
                concept=concept,
                score=es_result["score"],
                vocabulary_name=vocabulary.name if vocabulary else "Unknown",
            )
        )

    return ConceptSearchResults(results=results, total=len(results))


@router.post(
    "/{dataset_id}/clusters/{cluster_id}/map",
    response_model=MessageOutput,
    status_code=status.HTTP_200_OK,
    summary="Map a cluster to a concept",
    description="Creates or updates a mapping between a cluster and a concept",
)
def map_cluster_to_concept(
    dataset_id: int,
    cluster_id: int,
    request: MapClusterRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """Manually map a cluster to a concept."""
    # Verify dataset ownership
    dataset = db.get(Dataset, dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    verify_dataset_ownership(dataset, current_user.id)

    # Get cluster
    cluster = db.get(Cluster, cluster_id)
    if not cluster or cluster.dataset_id != dataset_id:
        raise HTTPException(status_code=404, detail="Cluster not found")

    if not cluster.reviewed:
        raise HTTPException(
            status_code=400,
            detail="Cluster must be reviewed before mapping",
        )

    # Get concept
    concept = db.get(Concept, request.concept_id)
    if not concept:
        raise HTTPException(status_code=404, detail="Concept not found")

    # Check if mapping already exists
    existing_mapping = db.exec(
        select(SourceToConceptMap).where(SourceToConceptMap.cluster_id == cluster_id)
    ).first()

    if existing_mapping:
        # Update existing mapping
        existing_mapping.concept_id = request.concept_id
        existing_mapping.status = request.status
        existing_mapping.comment = request.comment
        existing_mapping.updated_at = datetime.now(timezone.utc)
        db.add(existing_mapping)
    else:
        # Create new mapping
        new_mapping = SourceToConceptMap(
            cluster_id=cluster_id,
            concept_id=request.concept_id,
            status=request.status,
            comment=request.comment,
        )
        db.add(new_mapping)

    db.commit()

    return MessageOutput(message="Cluster mapped successfully")


@router.delete(
    "/{dataset_id}/clusters/{cluster_id}/mapping",
    response_model=MessageOutput,
    status_code=status.HTTP_200_OK,
    summary="Remove cluster mapping",
    description="Deletes the mapping between a cluster and its concept",
)
def delete_cluster_mapping(
    dataset_id: int,
    cluster_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """Remove a cluster's mapping."""
    # Verify dataset ownership
    dataset = db.get(Dataset, dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    verify_dataset_ownership(dataset, current_user.id)

    # Get cluster
    cluster = db.get(Cluster, cluster_id)
    if not cluster or cluster.dataset_id != dataset_id:
        raise HTTPException(status_code=404, detail="Cluster not found")

    # Delete mapping
    mapping = db.exec(
        select(SourceToConceptMap).where(SourceToConceptMap.cluster_id == cluster_id)
    ).first()

    if not mapping:
        raise HTTPException(status_code=404, detail="Mapping not found")

    db.delete(mapping)
    db.commit()

    return MessageOutput(message="Mapping deleted successfully")


@router.post(
    "/{dataset_id}/auto-map-all",
    response_model=MappingJobStartResponse,
    status_code=status.HTTP_200_OK,
    summary="Start bulk auto-mapping for all clusters",
    description=(
        "Queues a background job that auto-maps every reviewed, unmapped cluster. "
        "Returns immediately with a job id; poll the status endpoint for progress."
    ),
)
def auto_map_all_clusters(
    dataset_id: int,
    request: AutoMapAllRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """Kick off bulk auto-mapping and return a pollable job id."""
    # Verify dataset ownership
    dataset = db.get(Dataset, dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    verify_dataset_ownership(dataset, current_user.id)

    active_job = db.exec(
        select(MappingJob)
        .where(MappingJob.dataset_id == dataset_id)
        .where((MappingJob.status == "pending") | (MappingJob.status == "running"))
    ).first()
    if active_job is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An auto-map job is already running for this dataset",
        )

    # Total is the number of reviewed clusters processed by the loop; the worker
    # ticks `completed` once per cluster (mapped, failed, or already-mapped skip).
    cluster_query = select(Cluster).where(Cluster.dataset_id == dataset_id)
    cluster_query = cluster_query.where(Cluster.reviewed == True)  # noqa: E712
    if request.label:
        cluster_query = cluster_query.where(Cluster.label == request.label)

    total = len(db.exec(cluster_query).all())

    job = MappingJob(
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

        return MappingJobStartResponse(
            job_id=job.id,
            dataset_id=dataset_id,
            total=job.total,
            status=job.status,
        )

    background_tasks.add_task(
        run_auto_map_all_job,
        job_id=job.id,
        dataset_id=dataset_id,
        vocabulary_ids=request.vocabulary_ids,
        label=request.label,
        use_cluster_terms=request.use_cluster_terms,
        search_type=request.search_type,
    )

    return MappingJobStartResponse(
        job_id=job.id,
        dataset_id=dataset_id,
        total=total,
        status=job.status,
    )


@router.get(
    "/{dataset_id}/auto-map-all/active",
    response_model=Optional[MappingJobStatusResponse],
)
def get_active_auto_map_job(
    dataset_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """Return the latest pending/running auto-map job for the dataset, or null."""
    dataset = db.get(Dataset, dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    verify_dataset_ownership(dataset, current_user.id)

    job = db.exec(
        select(MappingJob)
        .where(MappingJob.dataset_id == dataset_id)
        .where((MappingJob.status == "pending") | (MappingJob.status == "running"))
        .order_by(MappingJob.created_at.desc())
    ).first()

    if job is None:
        return None

    return _mapping_job_status(job)


@router.get(
    "/{dataset_id}/auto-map-all/{job_id}/status",
    response_model=MappingJobStatusResponse,
)
def get_auto_map_job_status(
    dataset_id: int,
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """Return progress for an auto-map-all job."""
    dataset = db.get(Dataset, dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    verify_dataset_ownership(dataset, current_user.id)

    job = db.get(MappingJob, job_id)
    if job is None or job.dataset_id != dataset_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Auto-map job not found for this dataset",
        )

    return _mapping_job_status(job)


@router.post(
    "/{dataset_id}/auto-map-all/{job_id}/cancel",
    response_model=MessageOutput,
)
def cancel_auto_map_job(
    dataset_id: int,
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """Request cancellation of an auto-map job. Already-created mappings remain."""
    dataset = db.get(Dataset, dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    verify_dataset_ownership(dataset, current_user.id)

    job = db.get(MappingJob, job_id)
    if job is None or job.dataset_id != dataset_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Auto-map job not found for this dataset",
        )

    if job.status in {"completed", "failed", "cancelled"}:
        return MessageOutput(message=f"Job already {job.status}")

    job.status = "cancelled"
    job.updated_at = datetime.now(timezone.utc)
    db.add(job)
    db.commit()

    return MessageOutput(message="Cancellation requested")


def _mapping_job_status(job: MappingJob) -> MappingJobStatusResponse:
    """Build the polled status response from a MappingJob row."""
    return MappingJobStatusResponse(
        job_id=job.id,
        dataset_id=job.dataset_id,
        total=job.total,
        completed=job.completed,
        mapped_count=job.mapped_count,
        failed_count=job.failed_count,
        status=job.status,
        error_message=job.error_message,
    )


def run_auto_map_all_job(
    job_id: int,
    dataset_id: int,
    vocabulary_ids: list[int],
    label: Optional[str],
    use_cluster_terms: bool,
    search_type: str,
):
    """Background task that auto-maps every reviewed, unmapped cluster.

    Mirrors the extraction worker: flips the job to running, ticks `completed`
    per cluster committing as it goes, honours a `cancelled` status to break
    early, and records the final mapped/failed tallies on the job.
    """
    with Session(engine) as session:
        job = session.get(MappingJob, job_id)
        if job is None:
            return

        if job.status == "cancelled":
            return

        job.status = "running"
        job.updated_at = datetime.now(timezone.utc)
        session.add(job)
        session.commit()

        cluster_query = select(Cluster).where(Cluster.dataset_id == dataset_id)
        cluster_query = cluster_query.where(Cluster.reviewed == True)  # noqa: E712
        if label:
            cluster_query = cluster_query.where(Cluster.label == label)
        clusters = session.exec(cluster_query).all()

        mapped_count = 0
        failed_count = 0

        for cluster in clusters:
            session.refresh(job)
            if job.status == "cancelled":
                job.mapped_count = mapped_count
                job.failed_count = failed_count
                job.updated_at = datetime.now(timezone.utc)
                session.add(job)
                session.commit()
                return

            # Skip if already mapped (preserve the original server-side guard).
            existing_mapping = session.exec(
                select(SourceToConceptMap).where(
                    SourceToConceptMap.cluster_id == cluster.id
                )
            ).first()

            if not existing_mapping:
                try:
                    # Build search query
                    search_text = cluster.title

                    if use_cluster_terms and cluster.source_terms:
                        term_freq = defaultdict(int)
                        for term in cluster.source_terms:
                            term_freq[term.value] += 1

                        top_terms = sorted(
                            term_freq.items(), key=lambda x: x[1], reverse=True
                        )[:5]
                        search_text += " " + " ".join([term for term, _ in top_terms])

                    # Search for best match - choose method based on search_type
                    if search_type == "vector":
                        es_results, _ = indexer.search_concepts_vector(
                            query_text=search_text,
                            vocab_ids=vocabulary_ids,
                            limit=1,
                        )
                    else:
                        es_results, _ = indexer.search_concepts(
                            query_text=search_text,
                            vocab_ids=vocabulary_ids,
                            limit=1,
                        )

                    if es_results:
                        best_match = es_results[0]
                        concept = session.get(Concept, best_match["concept_id"])

                        if concept:
                            session.add(
                                SourceToConceptMap(
                                    cluster_id=cluster.id,
                                    concept_id=concept.id,
                                    status="pending",
                                )
                            )
                            mapped_count += 1
                        else:
                            failed_count += 1
                    else:
                        failed_count += 1

                except Exception as e:
                    print(f"Error mapping cluster {cluster.id}: {e}")
                    failed_count += 1

            job.completed += 1
            job.mapped_count = mapped_count
            job.failed_count = failed_count
            job.updated_at = datetime.now(timezone.utc)
            session.add(job)
            session.commit()

        job.status = "completed"
        job.mapped_count = mapped_count
        job.failed_count = failed_count
        job.updated_at = datetime.now(timezone.utc)
        session.add(job)
        session.commit()


@router.get(
    "/concepts/search",
    response_model=ConceptSearchResults,
    status_code=status.HTTP_200_OK,
    summary="Search concepts",
    description="Search for concepts across multiple vocabularies with filters",
)
def search_concepts(
    query: str,
    vocabulary_ids: str,  # Comma-separated IDs
    domain_id: Optional[str] = None,
    concept_class_id: Optional[str] = None,
    standard_concept: Optional[str] = None,
    search_type: str = "hybrid",  # "vector" or "hybrid"
    limit: int = 10,
    offset: int = 0,
    sort_by: str = "relevance",
    sort_order: str = "desc",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """Search for concepts."""
    # Parse vocabulary IDs
    vocab_ids = [int(id.strip()) for id in vocabulary_ids.split(",") if id.strip()]

    if not vocab_ids:
        raise HTTPException(status_code=400, detail="No vocabulary IDs provided")

    # Search using Elasticsearch - choose method based on search_type
    if search_type == "vector":
        es_results, total_hits = indexer.search_concepts_vector(
            query_text=query,
            vocab_ids=vocab_ids,
            limit=limit,
            offset=offset,
            domain_id=domain_id,
            concept_class_id=concept_class_id,
            standard_concept=standard_concept,
        )
    else:
        es_results, total_hits = indexer.search_concepts(
            query_text=query,
            vocab_ids=vocab_ids,
            limit=limit,
            offset=offset,
            sort_by=sort_by,
            sort_order=sort_order,
            domain_id=domain_id,
            concept_class_id=concept_class_id,
            standard_concept=standard_concept,
        )

    # Get concept details from database
    results = []
    for es_result in es_results:
        concept = db.get(Concept, es_result["concept_id"])
        if not concept:
            continue

        vocabulary = concept.vocabulary
        results.append(
            ConceptSearchResult(
                concept=concept,
                score=es_result["score"],
                vocabulary_name=vocabulary.name if vocabulary else "Unknown",
            )
        )

    # Calculate pagination metadata
    from app.schemas import create_pagination_metadata

    pagination = create_pagination_metadata(total_hits, limit, offset)

    return ConceptSearchResults(
        results=results, total=total_hits, pagination=pagination
    )


@router.get(
    "/concepts/{concept_id}/hierarchy",
    response_model=ConceptHierarchy,
    status_code=status.HTTP_200_OK,
    summary="Get concept hierarchy",
    description="Get concept details with parent/child relationships",
)
def get_concept_hierarchy(
    concept_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """Get concept hierarchy information."""
    concept = db.get(Concept, concept_id)
    if not concept:
        raise HTTPException(status_code=404, detail="Concept not found")

    # TODO: Implement parent/child relationships if they exist in the database
    # For now, return empty lists
    return ConceptHierarchy(
        concept=concept,
        parents=[],
        children=[],
        related_concepts=[],
    )


@router.get(
    "/{dataset_id}/mappings/export",
    response_class=StreamingResponse,
    status_code=status.HTTP_200_OK,
    summary="Export OMOP CDM tables",
    description="Export mappings as OMOP CDM tables in a ZIP of CSVs",
)
def export_mappings(
    dataset_id: int,
    status_filter: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """Export mappings as OMOP CDM ZIP.

    Generates separate CSV files per OMOP CDM table, routed by
    concept domain_id, and returns them as a single ZIP archive.
    """
    dataset = db.get(Dataset, dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    verify_dataset_ownership(dataset, current_user.id)

    zip_bytes, filename = build_omop_cdm_zip(dataset, db, status_filter)

    return StreamingResponse(
        iter([zip_bytes]),
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.post(
    "/{dataset_id}/mappings/import",
    response_model=MessageOutput,
    status_code=status.HTTP_200_OK,
    summary="Import mappings",
    description="Import cluster-to-concept mappings from CSV",
)
async def import_mappings(
    dataset_id: int,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """Import mappings from CSV file."""
    # Verify dataset ownership
    dataset = db.get(Dataset, dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    verify_dataset_ownership(dataset, current_user.id)

    # Read CSV
    content = await file.read()
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=400,
            detail="File is not valid UTF-8 encoded text. Please upload a UTF-8 CSV.",
        )

    reader = csv.DictReader(io.StringIO(text))

    # Validate required headers up front so a CSV missing them fails loudly
    # instead of silently skipping every row.
    required_columns = {"source_name", "target_concept_id"}
    headers = set(reader.fieldnames or [])
    missing_columns = required_columns - headers
    if missing_columns:
        raise HTTPException(
            status_code=400,
            detail=(
                "CSV is missing required column(s): "
                + ", ".join(sorted(missing_columns))
            ),
        )

    matched_count = 0
    created_count = 0
    skipped_count = 0

    for row in reader:
        try:
            # Find cluster by name
            cluster = db.exec(
                select(Cluster)
                .where(Cluster.dataset_id == dataset_id)
                .where(Cluster.title == row["source_name"])
            ).first()

            if not cluster:
                skipped_count += 1
                continue

            matched_count += 1

            # Get concept
            concept_id = int(row["target_concept_id"])
            concept = db.get(Concept, concept_id)

            if not concept:
                skipped_count += 1
                continue

            # Check if mapping exists
            existing_mapping = db.exec(
                select(SourceToConceptMap).where(
                    SourceToConceptMap.cluster_id == cluster.id
                )
            ).first()

            if existing_mapping:
                # Update existing
                existing_mapping.concept_id = concept_id
                existing_mapping.updated_at = datetime.now(timezone.utc)
                db.add(existing_mapping)
            else:
                # Create new
                new_mapping = SourceToConceptMap(
                    cluster_id=cluster.id,
                    concept_id=concept_id,
                    status=row.get("status", "pending"),
                )
                db.add(new_mapping)
                created_count += 1

        except Exception as e:
            print(f"Error importing row: {e}")
            skipped_count += 1

    db.commit()

    return MessageOutput(
        message=f"Import complete. Matched: {matched_count}, Created: {created_count}, Skipped: {skipped_count}"
    )
