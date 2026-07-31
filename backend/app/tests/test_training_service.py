"""Tests for training_service lifecycle: create, progress, evaluate, complete/fail/stop."""

from app.models_db import Evaluation, ModelTrainRecordLink, TrainingMetric, TrainingRun
from app.services import training_service as svc
from sqlmodel import select


def test_run_lifecycle_to_completed(session, sample_dataset, sample_record):
    run = svc.create_run(session, dataset_ids=[sample_dataset.id],
                         base_model="urchade/gliner_small-v2.1",
                         labels=["Drug"], val_ratio=0.1)
    assert run.status == "pending"
    assert run.dataset_id == sample_dataset.id
    assert svc.get_dataset_ids(session, run.id, role="train") == [sample_dataset.id]

    svc.mark_running(session, run.id)
    assert session.get(TrainingRun, run.id).status == "running"

    svc.add_epoch_metric(session, run.id, epoch=1, loss=0.5)
    svc.add_epoch_metric(session, run.id, epoch=2, loss=0.3)
    metrics = session.exec(select(TrainingMetric).where(TrainingMetric.run_id == run.id)).all()
    assert [m.loss for m in sorted(metrics, key=lambda x: x.epoch)] == [0.5, 0.3]

    svc.record_evaluation(session, run.id, {"Drug": {"exact_f1": 0.8, "relaxed_f1": 0.9}})
    model = svc.complete_run(session, run.id, output_path="/models/run.pt",
                             record_ids=[sample_record.id])

    refreshed = session.get(TrainingRun, run.id)
    assert refreshed.status == "completed"
    assert refreshed.model_id == model.id
    assert model.path == "/models/run.pt"
    assert model.base_model == "urchade/gliner_small-v2.1"

    evals = session.exec(select(Evaluation).where(Evaluation.model_id == model.id)).all()
    assert {e.label for e in evals} == {"Drug"}
    links = session.exec(
        select(ModelTrainRecordLink).where(ModelTrainRecordLink.model_id == model.id)
    ).all()
    assert {link.record_id for link in links} == {sample_record.id}


def test_fail_run_records_message(session, sample_dataset):
    run = svc.create_run(session, dataset_ids=[sample_dataset.id], base_model="b",
                         labels=["Drug"], val_ratio=0.0)
    svc.fail_run(session, run.id, "boom")
    refreshed = session.get(TrainingRun, run.id)
    assert refreshed.status == "failed"
    assert refreshed.error_message == "boom"


def test_stop_run(session, sample_dataset):
    run = svc.create_run(session, dataset_ids=[sample_dataset.id], base_model="b",
                         labels=["Drug"], val_ratio=0.0)
    svc.stop_run(session, run.id)
    assert session.get(TrainingRun, run.id).status == "stopped"


def test_create_run_multi_dataset_links(session, sample_dataset, sample_user):
    """Multiple training datasets are linked; the first is the primary."""
    from app.models_db import Dataset

    ds2 = Dataset(name="ds2", labels=["Drug"], user_id=sample_user.id)
    session.add(ds2)
    session.commit()
    session.refresh(ds2)

    run = svc.create_run(
        session,
        dataset_ids=[sample_dataset.id, ds2.id],
        base_model="b",
        labels=["Drug"],
        val_ratio=0.1,
        eval_dataset_ids=[ds2.id],
    )
    assert run.dataset_id == sample_dataset.id
    assert set(svc.get_dataset_ids(session, run.id, role="train")) == {sample_dataset.id, ds2.id}
    assert svc.get_dataset_ids(session, run.id, role="eval") == [ds2.id]

    # Deleting a run removes its dataset links.
    svc.delete_run(session, run.id)
    assert svc.get_dataset_ids(session, run.id, role="train") == []


def test_has_active_run_for_datasets(session, sample_dataset):
    """An active run is detected on any of its training datasets."""
    assert svc.has_active_run_for_datasets(session, [sample_dataset.id]) is False
    run = svc.create_run(session, dataset_ids=[sample_dataset.id], base_model="b",
                         labels=["Drug"], val_ratio=0.0)
    assert svc.has_active_run_for_datasets(session, [sample_dataset.id]) is True
    svc.stop_run(session, run.id)
    assert svc.has_active_run_for_datasets(session, [sample_dataset.id]) is False
