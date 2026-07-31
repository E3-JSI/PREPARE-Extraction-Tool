"""Regression tests for the dataset re-extraction background job.

Guards the fix for the re-run bug: a repeat full extraction must reprocess every
eligible record (unreviewed, no manual terms), not just records missed the first
time. Reviewed records and records with a manual term must be left untouched.

Runs against in-memory SQLite; the NER HTTP call is mocked.
"""

import os

os.environ.setdefault("DATABASE_URL", "postgresql://u:p@localhost:5432/db")
os.environ.setdefault("ELASTICSEARCH_URL", "http://localhost:9200")
os.environ.setdefault("SECRET_KEY", "test")
os.environ.setdefault("JWT_SECRET_KEY", "test")

from datetime import datetime, timezone

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import app.routes.v1.bioner as bioner
from app.interfaces import LabelsInput
from app.models_db import (
    Dataset,
    ExtractionJob,
    Model,
    Record,
    SourceTerm,
    SourceTermEx,
    User,
)


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


@pytest.fixture
def engine(monkeypatch):
    """Fresh in-memory DB, wired into the bioner module's module-level engine."""
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(eng)
    # The background job opens its own Session(engine) from this module global.
    monkeypatch.setattr(bioner, "engine", eng)
    yield eng
    SQLModel.metadata.drop_all(eng)


def _seed(engine):
    """Dataset with three records: auto-only (eligible), reviewed, and manual."""
    with Session(engine) as s:
        user = User(username="t", hashed_password="h")
        s.add(user)
        s.commit()
        s.refresh(user)

        ds = Dataset(name="ds", labels=["Drug"], user_id=user.id)
        model = Model(name="m", version="1")
        s.add(ds)
        s.add(model)
        s.commit()
        s.refresh(ds)
        s.refresh(model)

        def mk_record(text, reviewed=False):
            r = Record(
                patient_id="p",
                visit_date=datetime.now(timezone.utc),
                text=text,
                dataset_id=ds.id,
                reviewed=reviewed,
            )
            s.add(r)
            s.commit()
            s.refresh(r)
            return r

        rec_auto = mk_record("aspirin 100mg")
        rec_reviewed = mk_record("ibuprofen", reviewed=True)
        rec_manual = mk_record("paracetamol")

        # Stale auto term on the eligible record; NER will NOT return it, proving
        # a re-run refreshes (deletes + re-extracts) rather than accumulating.
        s.add(
            SourceTerm(
                record_id=rec_auto.id,
                value="stale",
                label="Drug",
                start_position=0,
                end_position=5,
                automatically_extracted=True,
            )
        )
        # Reviewed record keeps its auto term (record is skipped entirely).
        s.add(
            SourceTerm(
                record_id=rec_reviewed.id,
                value="ibuprofen",
                label="Drug",
                start_position=0,
                end_position=9,
                automatically_extracted=True,
            )
        )
        # Manual term: editing/creating flips automatically_extracted to False.
        s.add(
            SourceTerm(
                record_id=rec_manual.id,
                value="paracetamol",
                label="Drug",
                start_position=0,
                end_position=11,
                automatically_extracted=False,
            )
        )
        s.commit()
        return ds.id, model.id, rec_auto.id, rec_reviewed.id, rec_manual.id


def _run_job(engine, dataset_id, model_id):
    with Session(engine) as s:
        job = ExtractionJob(
            dataset_id=dataset_id,
            model_id=model_id,
            total=0,
            completed=0,
            status="pending",
            currently_used=True,
        )
        s.add(job)
        s.commit()
        s.refresh(job)
        job_id = job.id

    bioner.run_dataset_extraction_job(
        job_id=job_id,
        dataset_id=dataset_id,
        labels=["Drug"],
    )
    return job_id


def _auto_values(session, record_id):
    return sorted(
        t.value
        for t in session.exec(
            select(SourceTerm)
            .where(SourceTerm.record_id == record_id)
            .where(SourceTerm.automatically_extracted == True)  # noqa: E712
        ).all()
    )


def test_reextraction_reprocesses_eligible_records_on_rerun(engine, monkeypatch):
    dataset_id, model_id, rec_auto, rec_reviewed, rec_manual = _seed(engine)

    called_texts = []

    def fake_post(url, json=None, timeout=None):
        called_texts.append(json["medical_text"])
        return _FakeResponse(
            [{"text": "aspirin", "label": "Drug", "start": 0, "end": 7, "score": 0.9}]
        )

    monkeypatch.setattr(bioner.requests, "post", fake_post)

    # First run: only the eligible record hits NER.
    _run_job(engine, dataset_id, model_id)
    assert called_texts == ["aspirin 100mg"]

    with Session(engine) as s:
        # Stale auto term replaced by the fresh NER output.
        assert _auto_values(s, rec_auto) == ["aspirin"]
        # Reviewed and manual records untouched (no NER call, terms preserved).
        assert _auto_values(s, rec_reviewed) == ["ibuprofen"]
        manual = s.exec(
            select(SourceTerm).where(SourceTerm.record_id == rec_manual)
        ).all()
        assert [t.value for t in manual] == ["paracetamol"]
        assert manual[0].automatically_extracted is False

    # Second run over the same dataset: the eligible record is reprocessed again
    # (the old SourceTermEx-history skip would have no-op'd it), while reviewed and
    # manual records are still skipped.
    called_texts.clear()
    _run_job(engine, dataset_id, model_id)
    assert called_texts == ["aspirin 100mg"]

    with Session(engine) as s:
        # No duplicate accumulation: still a single fresh auto term.
        assert _auto_values(s, rec_auto) == ["aspirin"]
        assert _auto_values(s, rec_reviewed) == ["ibuprofen"]
        manual = s.exec(
            select(SourceTerm).where(SourceTerm.record_id == rec_manual)
        ).all()
        assert [t.value for t in manual] == ["paracetamol"]

    # Extraction owns only SourceTerm; SourceTermEx is never written here.
    with Session(engine) as s:
        assert s.exec(select(SourceTermEx)).all() == []


def test_single_record_extract_writes_only_source_term(engine, monkeypatch):
    dataset_id, model_id, rec_auto, rec_reviewed, rec_manual = _seed(engine)

    calls = []

    def fake_post(url, json=None, timeout=None):
        calls.append(json["medical_text"])
        return _FakeResponse(
            [{"text": "aspirin", "label": "Drug", "start": 0, "end": 7, "score": 0.9}]
        )

    monkeypatch.setattr(bioner.requests, "post", fake_post)

    with Session(engine) as s:
        user = s.exec(select(User)).first()

        # First extract: stale auto term refreshed, only SourceTerm written.
        bioner.extract_entities_from_record(
            dataset_id=dataset_id,
            record_id=rec_auto,
            labels=LabelsInput(labels=["Drug"]),
            current_user=user,
            db=s,
        )
        assert _auto_values(s, rec_auto) == ["aspirin"]
        assert s.exec(select(SourceTermEx)).all() == []

        # Explicit re-extract always re-runs the model (no cached-restore shortcut).
        bioner.extract_entities_from_record(
            dataset_id=dataset_id,
            record_id=rec_auto,
            labels=LabelsInput(labels=["Drug"]),
            current_user=user,
            db=s,
        )
        assert calls == ["aspirin 100mg", "aspirin 100mg"]
        assert _auto_values(s, rec_auto) == ["aspirin"]
        assert s.exec(select(SourceTermEx)).all() == []
