from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from app.core.model_registry import model_registry
from app.core.database import (
    get_session,
    User,
    Dataset,
    SourceTerm,
    Cluster,
    Record,
)
from app.models_db import SourceTermLink
from app.routes.v1.auth import get_current_user
from app.schemas import (
    MessageOutput,
    SourceTermOutput,
    SourceTermUpdate,
    SourceTermLinkCreate,
    SourceTermLinkResponse,
    BatchTermToClusterMapping,
)
from app.library.record_processing import link_dates_for_record

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
# Route definitions
# ================================================

router = APIRouter()


@router.post("/{term_id}/auto-map-to-cluster", response_model=MessageOutput)
def auto_map_source_term_to_cluster(
    term_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    # --- 1. Load term ---
    source_term = db.get(SourceTerm, term_id)
    if not source_term:
        raise HTTPException(404, "SourceTerm not found")

    verify_dataset_ownership(source_term.record.dataset, current_user.id)

    dataset_id = source_term.record.dataset_id

    # --- 2. Load all clusters for this dataset + label ---
    clusters = db.exec(
        select(Cluster)
        .where(Cluster.dataset_id == dataset_id)
        .where(Cluster.label == source_term.label)
    ).all()

    if not clusters:
        # No clusters yet → create new
        new_cluster = Cluster(
            dataset_id=dataset_id,
            label=source_term.label,
            title=source_term.value,
        )
        db.add(new_cluster)
        db.commit()
        db.refresh(new_cluster)

        source_term.cluster_id = new_cluster.id
        db.add(source_term)
        db.commit()

        return MessageOutput(
            message=f"Created new cluster {new_cluster.id} (no existing clusters)."
        )

    # --- 3. Use embedding model instead of TF-IDF ---
    embedding_model = model_registry.get_model("embedding_sentence")

    # Cluster representatives = cluster titles
    cluster_titles = [c.title for c in clusters]

    # Get embeddings
    cluster_vectors = embedding_model.embed(cluster_titles)
    source_term_vector = embedding_model.embed([source_term.value])[0]

    # --- 4. Compute cosine similarity ---
    from sklearn.metrics.pairwise import cosine_similarity

    sims = cosine_similarity([source_term_vector], cluster_vectors)[0]

    best_idx = sims.argmax()
    best_sim = sims[best_idx]
    best_cluster = clusters[best_idx]

    # --- 5. Threshold decision ---
    SIM_THRESHOLD = 0.35  # Can tune later

    if best_sim >= SIM_THRESHOLD:
        # Assign to existing cluster
        source_term.cluster_id = best_cluster.id
        db.add(source_term)
        db.commit()

        return MessageOutput(
            message=f"Assigned to existing cluster {best_cluster.id} (sim={best_sim:.2f})"
        )

    else:
        # --- 6. Create a new cluster ---
        new_cluster = Cluster(
            dataset_id=dataset_id, label=source_term.label, title=source_term.value
        )
        db.add(new_cluster)
        db.commit()
        db.refresh(new_cluster)

        source_term.cluster_id = new_cluster.id
        db.add(source_term)
        db.commit()

        return MessageOutput(
            message=f"Created new cluster {new_cluster.id} (sim={best_sim:.2f})"
        )


@router.post("/batch-map-clusters", response_model=MessageOutput)
def batch_map_source_terms_to_clusters(
    input: BatchTermToClusterMapping,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """
    Bulk mapping of source terms to clusters.
    """
    if not input.mappings:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="No mappings provided"
        )

    updated_count = 0
    for mapping in input.mappings:
        source_term_id = mapping.term_id
        cluster_id = mapping.cluster_id

        source_term = db.get(SourceTerm, source_term_id)
        if not source_term:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Source term {source_term_id} not found",
            )
        # Verify ownership through term -> record -> dataset -> user
        verify_dataset_ownership(source_term.record.dataset, current_user.id)

        cluster = db.get(Cluster, cluster_id)
        if not cluster:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Cluster {cluster_id} not found",
            )
        # Verify ownership through cluster -> dataset -> user
        verify_dataset_ownership(cluster.dataset, current_user.id)

        source_term.cluster_id = cluster.id

        db.add(source_term)
        updated_count += 1

    db.commit()

    return MessageOutput(message=f"Successfully mapped {updated_count} terms")


@router.get(
    "/{term_id}",
    response_model=SourceTermOutput,
    status_code=status.HTTP_200_OK,
    summary="Get a specific source term",
    description="Retrieves a single source term by its ID",
    response_description="The requested source term",
)
def get_source_term(
    term_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    source_term = db.get(SourceTerm, term_id)
    if source_term is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Source term not found"
        )

    # Verify ownership through source term -> record -> dataset -> user
    verify_dataset_ownership(source_term.record.dataset, current_user.id)

    return SourceTermOutput(source_term=source_term)


@router.patch(
    "/{term_id}",
    response_model=SourceTermOutput,
    status_code=status.HTTP_200_OK,
    summary="Update a source term",
    description="Updates a source term's label",
    response_description="The updated source term",
)
def update_source_term(
    term_id: int,
    update_data: SourceTermUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    source_term = db.get(SourceTerm, term_id)
    if source_term is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Source term not found"
        )

    # Verify ownership through source term -> record -> dataset -> user
    verify_dataset_ownership(source_term.record.dataset, current_user.id)

    # Update fields if provided
    if update_data.label is not None:
        source_term.label = update_data.label
    # If the update explicitly included linked_visit_date (even if null), apply it
    # and mark this term as manually overridden so automatic linking won't overwrite it.
    fields_set = getattr(update_data, "__fields_set__", None)
    manually_set_date = False
    if fields_set is not None and "linked_visit_date" in fields_set:
        source_term.linked_visit_date = update_data.linked_visit_date
        source_term.manual_linked_visit_date = True
        source_term.linked_date_term_id = None
        manually_set_date = True

    db.add(source_term)
    db.flush()
    record = source_term.record or db.get(Record, source_term.record_id)
    # Re-run automatic linking only when the client did not explicitly set the linked_visit_date.
    if record is not None and not manually_set_date:
        link_dates_for_record(db, record)
    db.commit()
    db.refresh(source_term)

    return SourceTermOutput(source_term=source_term)


@router.delete(
    "/{term_id}",
    response_model=MessageOutput,
    status_code=status.HTTP_200_OK,
    summary="Delete a source term",
    description="Deletes a specific source term",
    response_description="Confirmation message that the source term was deleted successfully",
)
def delete_source_term(
    term_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    source_term = db.get(SourceTerm, term_id)
    if source_term is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Source term not found"
        )

    # Verify ownership through source term -> record -> dataset -> user
    verify_dataset_ownership(source_term.record.dataset, current_user.id)

    db.delete(source_term)
    db.flush()
    record = source_term.record or db.get(Record, source_term.record_id)
    if record is not None:
        link_dates_for_record(db, record)
    db.commit()

    return MessageOutput(message="Source term deleted successfully")


# ================================================
# Source term link routes
# ================================================


@router.post(
    "/links",
    response_model=SourceTermLinkResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a link between two source terms",
)
def create_source_term_link(
    body: SourceTermLinkCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    from_term = db.get(SourceTerm, body.from_term_id)
    to_term = db.get(SourceTerm, body.to_term_id)

    if from_term is None or to_term is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Source term not found"
        )
    if from_term.record_id != to_term.record_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Both terms must belong to the same record",
        )

    record = db.get(Record, from_term.record_id)
    dataset = db.get(Dataset, record.dataset_id)
    verify_dataset_ownership(dataset, current_user.id)

    # Validate the label pair is defined in dataset.label_relations
    relations = dataset.label_relations or []
    valid_pair = any(
        (r["from_label"] == from_term.label and r["to_label"] == to_term.label)
        or (r["from_label"] == to_term.label and r["to_label"] == from_term.label)
        for r in relations
    )
    if not valid_pair:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No relation defined between labels '{from_term.label}' and '{to_term.label}'",
        )

    # Normalise direction: from_label must be the relation's from_label
    canonical_from, canonical_to = from_term, to_term
    for r in relations:
        if r["from_label"] == to_term.label and r["to_label"] == from_term.label:
            canonical_from, canonical_to = to_term, from_term
            break

    # Prevent duplicate links
    existing = db.exec(
        select(SourceTermLink)
        .where(SourceTermLink.from_term_id == canonical_from.id)
        .where(SourceTermLink.to_term_id == canonical_to.id)
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Link already exists"
        )

    link = SourceTermLink(
        from_term_id=canonical_from.id,
        to_term_id=canonical_to.id,
        dataset_id=dataset.id,
    )
    db.add(link)
    db.commit()
    db.refresh(link)

    return SourceTermLinkResponse(
        id=link.id,
        from_term_id=canonical_from.id,
        to_term_id=canonical_to.id,
        from_term_value=canonical_from.value,
        to_term_value=canonical_to.value,
        from_term_label=canonical_from.label,
        to_term_label=canonical_to.label,
    )


@router.delete(
    "/links/{link_id}",
    response_model=MessageOutput,
    status_code=status.HTTP_200_OK,
    summary="Delete a source term link",
)
def delete_source_term_link(
    link_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    link = db.get(SourceTermLink, link_id)
    if link is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Link not found"
        )

    dataset = db.get(Dataset, link.dataset_id)
    verify_dataset_ownership(dataset, current_user.id)

    db.delete(link)
    db.commit()

    return MessageOutput(message="Link deleted successfully")


# ================================================
# Source term to cluster assignment routes
# ================================================


@router.post("/{term_id}/map-cluster/{cluster_id}", response_model=MessageOutput)
def map_source_term_to_cluster(
    term_id: int,
    cluster_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """
    Manually assign a SourceTerm to a cluster.

    This endpoint moves ALL SourceTerms with the same value (text) and label
    from the source location (cluster or unclustered) to the target cluster.
    This ensures consistency between frontend aggregated view and backend data.
    """
    source_term = db.get(SourceTerm, term_id)
    cluster = db.get(Cluster, cluster_id)

    if not source_term:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Source term {term_id} not found",
        )
    if not cluster:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Cluster {cluster_id} not found",
        )

    # Verify ownership through source term -> record -> dataset -> user
    verify_dataset_ownership(source_term.record.dataset, current_user.id)
    # Verify ownership through cluster -> dataset -> user
    verify_dataset_ownership(cluster.dataset, current_user.id)

    # Get dataset_id from the source term's record
    dataset_id = source_term.record.dataset_id
    source_cluster_id = source_term.cluster_id

    # Find ALL terms with the same value and label in the same dataset
    # that are in the same source location (same cluster or unclustered)
    terms_to_move = db.exec(
        select(SourceTerm)
        .join(Record)
        .where(Record.dataset_id == dataset_id)
        .where(SourceTerm.value == source_term.value)
        .where(SourceTerm.label == source_term.label)
        .where(SourceTerm.cluster_id == source_cluster_id)
    ).all()

    # Move all matching terms to the target cluster
    moved_count = 0
    for term in terms_to_move:
        term.cluster_id = cluster.id
        db.add(term)
        moved_count += 1

    # Check if source cluster is now empty and delete it
    if source_cluster_id is not None:
        source_cluster = db.get(Cluster, source_cluster_id)
        if source_cluster:
            # Refresh to get updated source_terms after the move
            db.flush()
            remaining_terms = db.exec(
                select(SourceTerm).where(SourceTerm.cluster_id == source_cluster_id)
            ).all()
            if len(remaining_terms) == 0:
                db.delete(source_cluster)

    db.commit()

    return MessageOutput(
        message=f"Moved {moved_count} term(s) with value '{source_term.value}' to cluster {cluster_id}"
    )


@router.post("/{term_id}/unmap-cluster", response_model=MessageOutput)
def unmap_source_term_from_cluster(
    term_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """
    Remove source term from its cluster.

    This endpoint removes ALL SourceTerms with the same value (text) and label
    from the cluster. If the cluster becomes empty after removal, it is deleted.
    This ensures consistency between frontend aggregated view and backend data.
    """
    source_term = db.get(SourceTerm, term_id)
    if not source_term:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Source term not found"
        )

    # Verify ownership through source term -> record -> dataset -> user
    verify_dataset_ownership(source_term.record.dataset, current_user.id)

    source_cluster_id = source_term.cluster_id
    if source_cluster_id is None:
        return MessageOutput(message="Source term is not in any cluster")

    # Get dataset_id from the source term's record
    dataset_id = source_term.record.dataset_id

    # Find ALL terms with the same value and label in this cluster
    terms_to_unmap = db.exec(
        select(SourceTerm)
        .join(Record)
        .where(Record.dataset_id == dataset_id)
        .where(SourceTerm.value == source_term.value)
        .where(SourceTerm.label == source_term.label)
        .where(SourceTerm.cluster_id == source_cluster_id)
    ).all()

    # Unmap all matching terms
    unmapped_count = 0
    for term in terms_to_unmap:
        term.cluster_id = None
        db.add(term)
        unmapped_count += 1

    # Check if cluster is now empty and delete it
    source_cluster = db.get(Cluster, source_cluster_id)
    if source_cluster:
        # Flush to see updated state
        db.flush()
        remaining_terms = db.exec(
            select(SourceTerm).where(SourceTerm.cluster_id == source_cluster_id)
        ).all()
        if len(remaining_terms) == 0:
            db.delete(source_cluster)

    db.commit()

    return MessageOutput(
        message=f"Unmapped {unmapped_count} term(s) with value '{source_term.value}' from cluster"
    )
