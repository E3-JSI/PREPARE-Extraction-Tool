from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session

from typing import List, Dict
from datetime import datetime, timezone

from app.core.model_registry import model_registry
from app.utils.vector_math import cosine_similarity as _cosine_sim
from app.utils.vector_math import mean_vector as _mean_vector

from sqlmodel import select
from app.models_db import ClusterMergeSuggestion, SourceTerm
from app.schemas import MergeSuggestionsOutput, MergeSuggestionResponse, ClusterShort

from app.core.database import get_session
from app.models_db import Dataset, User, Cluster
from app.routes.v1.auth import get_current_user
from app.schemas import (
    MessageOutput,
    ClusterOutput,
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


def _invalidate_suggestions_for_deleted_cluster(
    db: Session,
    deleted_cluster_id: int,
    *,
    reviewed_by_user_id: int,
    reviewed_at: datetime,
    skip_suggestion_id: int | None = None,
):
    """
    Reject any other PENDING merge suggestions that reference a cluster that was
    just deleted during a merge. Without this, those suggestions stay pending but
    point at a non-existent cluster, causing later accepts to 404 / be skipped.
    """
    stale = db.exec(
        select(ClusterMergeSuggestion)
        .where(ClusterMergeSuggestion.status == "pending")
        .where(
            (ClusterMergeSuggestion.cluster_a_id == deleted_cluster_id)
            | (ClusterMergeSuggestion.cluster_b_id == deleted_cluster_id)
        )
    ).all()
    for other in stale:
        if skip_suggestion_id is not None and other.id == skip_suggestion_id:
            continue
        other.status = "rejected"
        other.reviewed_at = reviewed_at
        other.reviewed_by_user_id = reviewed_by_user_id
        db.add(other)


# ================================================
# Clusters routes
# ================================================


@router.post(
    "/datasets/{dataset_id}/clusters/merge-suggestions/generate",
    response_model=MessageOutput,
    status_code=status.HTTP_201_CREATED,
)
def generate_merge_suggestions(
    dataset_id: int,
    label: str,
    threshold: float = 0.8,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """
    Create merge suggestions (pending) for clusters in a dataset+label.
    Does NOT merge anything automatically.
    """

    # 1) dataset ownership
    dataset = db.get(Dataset, dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    verify_dataset_ownership(dataset, current_user.id)

    # 2) get clusters for dataset+label
    clusters = db.exec(
        select(Cluster)
        .where(Cluster.dataset_id == dataset_id)
        .where(Cluster.label == label)
    ).all()

    if len(clusters) < 2:
        return MessageOutput(message="Not enough clusters to generate suggestions")

    cluster_ids = [c.id for c in clusters]

    # 3) load source terms inside these clusters
    terms = db.exec(
        select(SourceTerm).where(SourceTerm.cluster_id.in_(cluster_ids))
    ).all()

    cluster_texts: Dict[int, List[str]] = {cid: [] for cid in cluster_ids}
    for t in terms:
        if t.cluster_id is None:
            continue
        txt = (t.value or "").strip()
        if txt:
            cluster_texts[int(t.cluster_id)].append(txt)

    # 4) embed all term texts
    all_texts: List[str] = []
    owner_cluster: List[int] = []
    for cid, texts in cluster_texts.items():
        for s in texts:
            all_texts.append(s)
            owner_cluster.append(cid)

    if not all_texts:
        return MessageOutput(message="No source terms to embed")

    embedding_model = model_registry.get_model("embedding_sentence")
    if hasattr(embedding_model, "embed"):
        emb = embedding_model.embed(all_texts)
    else:
        emb = embedding_model.encode(all_texts)

    emb_list: List[List[float]] = emb.tolist() if hasattr(emb, "tolist") else emb

    # 5) compute centroid per cluster
    cluster_vectors: Dict[int, List[List[float]]] = {cid: [] for cid in cluster_ids}
    for vec, cid in zip(emb_list, owner_cluster):
        cluster_vectors[cid].append(vec)

    centroids: Dict[int, List[float]] = {}
    for cid, vecs in cluster_vectors.items():
        if vecs:
            centroids[cid] = _mean_vector(vecs)

    # 6) avoid duplicates
    existing = db.exec(
        select(ClusterMergeSuggestion)
        .where(ClusterMergeSuggestion.dataset_id == dataset_id)
        .where(ClusterMergeSuggestion.label == label)
    ).all()

    existing_pairs = set()
    for s in existing:
        a, b = int(s.cluster_a_id), int(s.cluster_b_id)
        existing_pairs.add((min(a, b), max(a, b)))

    # 7) create new suggestions based on centroid similarity
    created = 0
    ids = sorted(centroids.keys())
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            a = ids[i]
            b = ids[j]
            pair = (min(a, b), max(a, b))
            if pair in existing_pairs:
                continue

            sim = _cosine_sim(centroids[a], centroids[b])
            if sim >= threshold:
                db.add(
                    ClusterMergeSuggestion(
                        dataset_id=dataset_id,
                        label=label,
                        cluster_a_id=pair[0],
                        cluster_b_id=pair[1],
                        score=float(sim),
                        method="centroid",
                        status="pending",
                    )
                )
                existing_pairs.add(pair)
                created += 1

    db.commit()
    return MessageOutput(message=f"Generated {created} merge suggestions")


@router.get(
    "/datasets/{dataset_id}/clusters/merge-suggestions",
    response_model=MergeSuggestionsOutput,
)
def list_merge_suggestions(
    dataset_id: int,
    label: str,
    status_filter: str = "pending",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """
    List merge suggestions for a dataset and label.
    Default: only pending suggestions.
    """
    dataset = db.get(Dataset, dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")

    verify_dataset_ownership(dataset, current_user.id)

    suggestions = db.exec(
        select(ClusterMergeSuggestion)
        .where(ClusterMergeSuggestion.dataset_id == dataset_id)
        .where(ClusterMergeSuggestion.label == label)
        .where(ClusterMergeSuggestion.status == status_filter)
        .order_by(ClusterMergeSuggestion.score.desc())
    ).all()

    result: List[MergeSuggestionResponse] = []
    for s in suggestions:
        a = db.get(Cluster, s.cluster_a_id)
        b = db.get(Cluster, s.cluster_b_id)
        if not a or not b:
            continue

        result.append(
            MergeSuggestionResponse(
                id=s.id,
                dataset_id=s.dataset_id,
                label=s.label,
                method=s.method,
                score=s.score,
                status=s.status,
                created_at=s.created_at,
                cluster_a=ClusterShort(
                    id=a.id,
                    title=a.title,
                    label=a.label,
                    dataset_id=a.dataset_id,
                ),
                cluster_b=ClusterShort(
                    id=b.id,
                    title=b.title,
                    label=b.label,
                    dataset_id=b.dataset_id,
                ),
            )
        )

    return MergeSuggestionsOutput(suggestions=result)


@router.post(
    "/datasets/{dataset_id}/clusters/merge-suggestions/{suggestion_id}/reject",
    response_model=MessageOutput,
)
def reject_merge_suggestion(
    dataset_id: int,
    suggestion_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    suggestion = db.get(ClusterMergeSuggestion, suggestion_id)
    if not suggestion or suggestion.dataset_id != dataset_id:
        raise HTTPException(status_code=404, detail="Suggestion not found")

    dataset = db.get(Dataset, dataset_id)
    verify_dataset_ownership(dataset, current_user.id)

    suggestion.status = "rejected"
    suggestion.reviewed_at = datetime.now(timezone.utc)
    suggestion.reviewed_by_user_id = current_user.id

    db.add(suggestion)
    db.commit()

    return MessageOutput(message="Suggestion rejected")


@router.post(
    "/datasets/{dataset_id}/clusters/merge-suggestions/{suggestion_id}/accept",
    response_model=MessageOutput,
)
def accept_merge_suggestion(
    dataset_id: int,
    suggestion_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    suggestion = db.get(ClusterMergeSuggestion, suggestion_id)
    if not suggestion or suggestion.dataset_id != dataset_id:
        raise HTTPException(status_code=404, detail="Suggestion not found")

    dataset = db.get(Dataset, dataset_id)
    verify_dataset_ownership(dataset, current_user.id)

    cluster_a = db.get(Cluster, suggestion.cluster_a_id)
    cluster_b = db.get(Cluster, suggestion.cluster_b_id)
    if not cluster_a or not cluster_b:
        raise HTTPException(status_code=404, detail="Cluster not found")

    # 1) Move all terms from B to A
    terms_b = db.exec(
        select(SourceTerm).where(SourceTerm.cluster_id == cluster_b.id)
    ).all()
    for t in terms_b:
        t.cluster_id = cluster_a.id
        db.add(t)

    # 2) Delete cluster B
    deleted_cluster_id = cluster_b.id
    db.delete(cluster_b)

    # 3) Mark suggestion accepted
    now = datetime.now(timezone.utc)
    suggestion.status = "accepted"
    suggestion.reviewed_at = now
    suggestion.reviewed_by_user_id = current_user.id
    db.add(suggestion)

    # 4) Invalidate other pending suggestions referencing the deleted cluster
    _invalidate_suggestions_for_deleted_cluster(
        db,
        deleted_cluster_id,
        reviewed_by_user_id=current_user.id,
        reviewed_at=now,
        skip_suggestion_id=suggestion.id,
    )

    db.commit()

    return MessageOutput(message="Clusters merged (accepted suggestion)")


@router.post(
    "/datasets/{dataset_id}/clusters/merge-suggestions/accept-all",
    response_model=MessageOutput,
)
def accept_all_merge_suggestions(
    dataset_id: int,
    label: str,
    status_filter: str = "pending",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """
    Accept (merge) ALL merge suggedtions for dataset+label with status=pending.
    Merges clusters and marks suggestions as accepted.
    """

    # 1) dataset ownership!
    dataset = db.get(Dataset, dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    verify_dataset_ownership(dataset, current_user.id)

    # 2) load pending suggestions
    suggestions = db.exec(
        select(ClusterMergeSuggestion)
        .where(ClusterMergeSuggestion.dataset_id == dataset_id)
        .where(ClusterMergeSuggestion.label == label)
        .where(ClusterMergeSuggestion.status == status_filter)
        .order_by(ClusterMergeSuggestion.score.desc())
    ).all()

    if not suggestions:
        return MessageOutput(message="No pending suggestions to accept")

    now = datetime.now(timezone.utc)
    accepted = 0
    skipped = 0

    for s in suggestions:
        # Clusters might already be merged/deleted by earlieriterations
        cluster_a = db.get(Cluster, s.cluster_a_id)
        cluster_b = db.get(Cluster, s.cluster_b_id)

        # If one cluster is missing -> cannot merge; mark as rejected or skip
        if not cluster_a or not cluster_b:
            skipped += 1
            # Option A: mark rejrcted so it doesn't stay pending forever? 
            s.status = "rejected"
            s.reviewed_at = now
            s.reviewed_by_user_id = current_user.id
            db.add(s)
            continue

        # Move all terms from B to A
        terms_b = db.exec(
            select(SourceTerm).where(SourceTerm.cluster_id == cluster_b.id)
        ).all()
        for t in terms_b:
            t.cluster_id = cluster_a.id
            db.add(t)

        # Delete cluster B
        deleted_cluster_id = cluster_b.id
        db.delete(cluster_b)

        # Mark suggestion accepted
        s.status = "accepted"
        s.reviewed_at = now
        s.reviewed_by_user_id = current_user.id
        db.add(s)

        # Invalidate other pending suggestions referencing the deleted cluster
        _invalidate_suggestions_for_deleted_cluster(
            db,
            deleted_cluster_id,
            reviewed_by_user_id=current_user.id,
            reviewed_at=now,
            skip_suggestion_id=s.id,
        )

        accepted += 1

    db.commit()
    return MessageOutput(message=f"Accepted {accepted} suggestions, skipped {skipped}")

@router.post(
    "/datasets/{dataset_id}/clusters/merge-suggestions/reject-all",
    response_model=MessageOutput,
)
def reject_all_merge_suggestions(
    dataset_id: int,
    label: str,
    status_filter: str = "pending",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """
    Reject ALL merge suggestions for dataset+label with status=pending.
    Does not merge anything.
    """

    dataset = db.get(Dataset, dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    verify_dataset_ownership(dataset, current_user.id)

    suggestions = db.exec(
        select(ClusterMergeSuggestion)
        .where(ClusterMergeSuggestion.dataset_id == dataset_id)
        .where(ClusterMergeSuggestion.label == label)
        .where(ClusterMergeSuggestion.status == status_filter)
    ).all()

    if not suggestions:
        return MessageOutput(message="No pending suggestions to reject")

    now = datetime.now(timezone.utc)
    for s in suggestions:
        s.status = "rejected"
        s.reviewed_at = now
        s.reviewed_by_user_id = current_user.id
        db.add(s)

    db.commit()
    return MessageOutput(message=f"Rejected {len(suggestions)} suggestions")



@router.get("/{cluster_id}", response_model=ClusterOutput)
def get_cluster(
    cluster_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """Returns details of a single cluster, including its source terms"""

    cluster = db.get(Cluster, cluster_id)
    if not cluster:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Cluster not found"
        )

    verify_dataset_ownership(cluster.dataset, current_user.id)

    return ClusterOutput(cluster=cluster)


@router.put("/{cluster_id}", response_model=MessageOutput)
def rename_cluster(
    cluster_id: int,
    title: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """Rename a cluster (title)"""

    cluster = db.get(Cluster, cluster_id)
    if not cluster:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Cluster not found"
        )

    verify_dataset_ownership(cluster.dataset, current_user.id)

    cluster.title = title
    db.add(cluster)
    db.commit()

    return MessageOutput(message=f"Cluster renamed to {title}")


@router.delete("/{cluster_id}", response_model=MessageOutput)
def delete_cluster(
    cluster_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """
    Delete a cluster.
    All SourceTerms in this cluster get cluster_id = NULL.
    """

    cluster = db.get(Cluster, cluster_id)
    if not cluster:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Cluster not found"
        )

    verify_dataset_ownership(cluster.dataset, current_user.id)

    # remove cluster assignment from terms
    for term in cluster.source_terms:
        term.cluster_id = None
        db.add(term)

    db.delete(cluster)
    db.commit()

    return MessageOutput(message="Cluster deleted")
