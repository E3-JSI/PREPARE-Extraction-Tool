"""Persist and read per-label NER evaluation results."""

from typing import Any, Dict, Optional

from sqlmodel import Session, select

from app.models_db import Evaluation

# Aggregate rows produced by classification reports; not real entity labels.
AGGREGATE_LABELS = {"micro avg", "macro avg", "weighted avg"}


def _read_f1(metrics: Dict[str, Any]) -> Optional[float]:
    """Pull an F1-like score from a per-label metric mapping, if present."""
    for key in ("exact_f1", "f1", "relaxed_f1"):
        value = metrics.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return None


def compute_macro_f1(per_label: Dict[str, Dict[str, Any]]) -> Optional[float]:
    """Compute an overall macro-F1 from a per-label evaluation mapping.

    Prefers an explicit "macro avg" row if the backend already provides one;
    otherwise averages the per-label F1 scores across real (non-aggregate)
    labels. Returns None when no usable score is available.

    Args:
        per_label (Dict[str, Dict[str, Any]]): Label -> metric mapping.

    Returns:
        Optional[float]: Macro-F1 in [0, 1], or None if not computable.
    """
    if not per_label:
        return None

    for label, metrics in per_label.items():
        if label.lower() == "macro avg" and isinstance(metrics, dict):
            macro = _read_f1(metrics)
            if macro is not None:
                return macro

    scores = [
        f1
        for label, metrics in per_label.items()
        if label.lower() not in AGGREGATE_LABELS
        and isinstance(metrics, dict)
        and (f1 := _read_f1(metrics)) is not None
    ]
    if not scores:
        return None
    return sum(scores) / len(scores)


def store_evaluation(
    db: Session,
    *,
    model_id: int,
    dataset_id: int,
    per_label: Dict[str, Dict[str, Any]],
) -> None:
    """Replace evaluation rows for a model with one row per label.

    Args:
        db (Session): Active DB session.
        model_id (int): Model the evaluation belongs to.
        dataset_id (int): Dataset the model was evaluated on.
        per_label (Dict[str, Dict[str, Any]]): Label -> metric mapping. Each
            metric mapping is stored verbatim as flexible JSON (e.g. exact_f1,
            relaxed_f1, precision, recall) and may also carry per-label error
            analysis (``fp``, ``fn`` counts and a bounded ``examples`` list) for
            newer runs; older runs simply omit those keys.
    """
    existing = db.exec(select(Evaluation).where(Evaluation.model_id == model_id)).all()
    for row in existing:
        db.delete(row)
    db.flush()
    for label, score in per_label.items():
        db.add(Evaluation(label=label, score=score, dataset_id=dataset_id, model_id=model_id))
    db.commit()


def get_per_label(db: Session, model_id: int) -> Dict[str, Dict[str, Any]]:
    """Return {label: score} for a model's evaluation.

    Args:
        db (Session): Active DB session.
        model_id (int): Model id.

    Returns:
        Dict[str, Dict[str, Any]]: Label -> metric mapping.
    """
    rows = db.exec(select(Evaluation).where(Evaluation.model_id == model_id)).all()
    return {row.label: row.score for row in rows}
