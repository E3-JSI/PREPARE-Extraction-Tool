"""Tests for evaluation_service: store and retrieve per-label NER evaluation results."""

from app.services import evaluation_service as svc


def test_store_and_get_per_label(session, sample_dataset, sample_model):
    per_label = {
        "Drug": {"exact_f1": 0.8, "relaxed_f1": 0.9, "precision": 0.85, "recall": 0.75},
        "Diagnosis": {"exact_f1": 0.6, "relaxed_f1": 0.7, "precision": 0.6, "recall": 0.6},
    }
    svc.store_evaluation(
        session, model_id=sample_model.id, dataset_id=sample_dataset.id, per_label=per_label
    )
    result = svc.get_per_label(session, sample_model.id)
    assert result["Drug"]["exact_f1"] == 0.8
    assert result["Diagnosis"]["relaxed_f1"] == 0.7


def test_store_evaluation_is_idempotent(session, sample_dataset, sample_model):
    svc.store_evaluation(session, model_id=sample_model.id, dataset_id=sample_dataset.id,
                         per_label={"Drug": {"exact_f1": 0.1}})
    svc.store_evaluation(session, model_id=sample_model.id, dataset_id=sample_dataset.id,
                         per_label={"Drug": {"exact_f1": 0.9}})
    result = svc.get_per_label(session, sample_model.id)
    assert result["Drug"]["exact_f1"] == 0.9  # replaced, not duplicated
    # exactly one row remains for this model
    from app.models_db import Evaluation
    from sqlmodel import select
    rows = session.exec(select(Evaluation).where(Evaluation.model_id == sample_model.id)).all()
    assert len(rows) == 1
