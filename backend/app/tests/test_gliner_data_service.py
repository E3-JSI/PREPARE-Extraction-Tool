"""Tests for the GLiNER training-data builder."""

from datetime import datetime, timezone

from sqlmodel import Session

from app.models_db import Record, SourceTerm
from app.services import gliner_data_service


def _make_record(session: Session, dataset_id: int, text: str, reviewed: bool) -> Record:
    """Persist and return a Record."""
    rec = Record(
        patient_id="p1",
        visit_date=datetime.now(timezone.utc),
        text=text,
        dataset_id=dataset_id,
        reviewed=reviewed,
    )
    session.add(rec)
    session.commit()
    session.refresh(rec)
    return rec


def _make_term(session: Session, record_id: int, value: str, label: str, start: int, end: int) -> None:
    """Persist a SourceTerm with character offsets."""
    term = SourceTerm(
        record_id=record_id,
        value=value,
        label=label,
        start_position=start,
        end_position=end,
    )
    session.add(term)
    session.commit()


def test_load_reviewed_training_data_builds_ner_triples(session, sample_dataset):
    """Reviewed record with labeled spans yields tokenized_text and ner triples."""
    text = "Patient takes aspirin and warfarin daily."
    rec = _make_record(session, sample_dataset.id, text, reviewed=True)
    # aspirin -> token index 2, warfarin -> token index 4
    _make_term(session, rec.id, "aspirin", "Drug", 14, 21)
    _make_term(session, rec.id, "warfarin", "Drug", 26, 34)

    data = gliner_data_service.load_reviewed_training_data(session, [sample_dataset.id])

    assert len(data) == 1
    example = data[0]
    assert example["tokenized_text"] == [
        "Patient",
        "takes",
        "aspirin",
        "and",
        "warfarin",
        "daily",
        ".",
    ]
    assert [2, 2, "Drug"] in example["ner"]
    assert [4, 4, "Drug"] in example["ner"]
    assert len(example["ner"]) == 2


def test_unreviewed_record_excluded(session, sample_dataset):
    """A record with reviewed=False is not included in training data."""
    text = "Patient takes aspirin and warfarin daily."
    rec = _make_record(session, sample_dataset.id, text, reviewed=False)
    _make_term(session, rec.id, "aspirin", "Drug", 14, 21)

    data = gliner_data_service.load_reviewed_training_data(session, [sample_dataset.id])

    assert data == []


def test_label_filter(session, sample_dataset):
    """Label filter restricts which source terms are included."""
    text = "Patient takes aspirin and warfarin daily."
    rec = _make_record(session, sample_dataset.id, text, reviewed=True)
    _make_term(session, rec.id, "aspirin", "Drug", 14, 21)
    _make_term(session, rec.id, "warfarin", "Diagnosis", 26, 34)

    data = gliner_data_service.load_reviewed_training_data(
        session, [sample_dataset.id], labels=["Drug"]
    )

    assert len(data) == 1
    assert data[0]["ner"] == [[2, 2, "Drug"]]
