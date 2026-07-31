"""Tests that TrainingRun.train_stats round-trips through the DB as JSON."""

from app.models_db import TrainingRun


def test_training_run_stores_train_stats_json(session, sample_dataset):
    run = TrainingRun(
        dataset_id=sample_dataset.id,
        base_model="urchade/gliner_multi-v2.1",
        labels=["Drug"],
        val_ratio=0.1,
        train_stats={
            "record_count": 12,
            "term_count": 40,
            "label_distribution": {"Drug": 40},
        },
    )
    session.add(run)
    session.commit()
    session.refresh(run)

    assert run.train_stats["record_count"] == 12
    assert run.train_stats["label_distribution"]["Drug"] == 40


def test_training_run_train_stats_defaults_to_none(session, sample_dataset):
    run = TrainingRun(
        dataset_id=sample_dataset.id,
        base_model="urchade/gliner_multi-v2.1",
        labels=["Drug"],
        val_ratio=0.0,
    )
    session.add(run)
    session.commit()
    session.refresh(run)

    assert run.train_stats is None
