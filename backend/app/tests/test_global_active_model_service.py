"""Tests for global active-model service helpers and the extraction-active guard."""

from app.models_db import ExtractionJob
from app.services import training_service
from app.services.extraction_lock import any_extraction_job_active


# ---------------------------------------------------------------------------
# Global active-model round-trip
# ---------------------------------------------------------------------------


def test_set_and_get_global_active_model(session, sample_model):
    """set_global_active_model → get_global_active_model round-trips correctly."""
    # AppSettings singleton is auto-created; initially no active model
    assert training_service.get_global_active_model(session) is None

    # Set a model
    training_service.set_global_active_model(session, sample_model.id)
    result = training_service.get_global_active_model(session)
    assert result is not None
    assert result.id == sample_model.id

    # Clear it
    training_service.set_global_active_model(session, None)
    assert training_service.get_global_active_model(session) is None


def test_get_app_settings_creates_singleton(session):
    """get_app_settings creates the row on first call and returns the same row on second."""
    row1 = training_service.get_app_settings(session)
    assert row1.id == 1
    assert row1.active_model_id is None

    row2 = training_service.get_app_settings(session)
    assert row2.id == row1.id


# ---------------------------------------------------------------------------
# Extraction-active guard
# ---------------------------------------------------------------------------


def test_any_extraction_job_active_false_when_empty(session):
    """Returns False when no extraction jobs exist."""
    assert any_extraction_job_active(session) is False


def test_any_extraction_job_active_true_for_pending(
    session, sample_dataset, sample_model
):
    """Returns True when a pending extraction job exists."""
    job = ExtractionJob(
        dataset_id=sample_dataset.id,
        model_id=sample_model.id,
        status="pending",
    )
    session.add(job)
    session.commit()

    assert any_extraction_job_active(session) is True


def test_any_extraction_job_active_true_for_running(
    session, sample_dataset, sample_model
):
    """Returns True when a running extraction job exists."""
    job = ExtractionJob(
        dataset_id=sample_dataset.id,
        model_id=sample_model.id,
        status="running",
    )
    session.add(job)
    session.commit()

    assert any_extraction_job_active(session) is True


def test_any_extraction_job_active_false_for_terminal_states(
    session, sample_dataset, sample_model
):
    """Returns False when only terminal (completed/failed) extraction jobs exist."""
    for status in ("completed", "failed"):
        job = ExtractionJob(
            dataset_id=sample_dataset.id,
            model_id=sample_model.id,
            status=status,
        )
        session.add(job)
    session.commit()

    assert any_extraction_job_active(session) is False
