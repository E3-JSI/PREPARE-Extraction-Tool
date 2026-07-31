"""Route tests for DELETE /bioner/models/{model_id}.

Deleting a model must work for rescan-"discovered" rows (no TrainingRun), remove
the on-disk folder via bioner, and clean up DB references (extraction/live-eval
job history, train-record links) that would otherwise block the row's deletion.
"""

import os

os.environ.setdefault("DATABASE_URL", "postgresql://u:p@localhost:5432/db")
os.environ.setdefault("ELASTICSEARCH_URL", "http://localhost:9200")
os.environ.setdefault("SECRET_KEY", "test")
os.environ.setdefault("JWT_SECRET_KEY", "test")

from datetime import datetime, timezone

import pytest
import requests
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.core.database import get_session
from app.main import app
from app.models_db import (
    AppSettings,
    Dataset,
    ExtractionJob,
    LiveEvalJob,
    Model,
    ModelTrainRecordLink,
    Record,
    TrainingRun,
    User,
)
from app.routes.v1.auth import get_current_user
from app.services import bioner_client


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    SQLModel.metadata.drop_all(engine)


@pytest.fixture
def client(db):
    user = User(username="t", hashed_password="h")
    db.add(user)
    db.commit()
    db.refresh(user)

    def _get_session_override():
        yield db

    app.dependency_overrides[get_session] = _get_session_override
    app.dependency_overrides[get_current_user] = lambda: user
    c = TestClient(app)
    yield c
    app.dependency_overrides.clear()


@pytest.fixture
def deleted_dirs(monkeypatch):
    """Capture bioner folder deletions instead of calling the service."""
    calls = []
    monkeypatch.setattr(bioner_client, "delete_model_dir", lambda d: calls.append(d))
    return calls


def _mk_model(db, name="m", path="/models/m", source="discovered"):
    model = Model(name=name, version="1", path=path, source=source)
    db.add(model)
    db.commit()
    db.refresh(model)
    return model


def test_delete_discovered_model_without_run(client, db, deleted_dirs):
    model = _mk_model(db, path="/models/run-1-20260101_000000")
    resp = client.delete(f"/api/v1/bioner/models/{model.id}")
    assert resp.status_code == 200
    assert db.get(Model, model.id) is None
    assert deleted_dirs == ["run-1-20260101_000000"]


def test_delete_cleans_job_history_and_links(client, db, deleted_dirs):
    user_id = db.exec(select(User)).first().id
    ds = Dataset(name="ds", labels=["Drug"], user_id=user_id)
    db.add(ds)
    db.commit()
    rec = Record(
        patient_id="p",
        visit_date=datetime.now(timezone.utc),
        text="x",
        dataset_id=ds.id,
    )
    db.add(rec)
    db.commit()

    model = _mk_model(db)
    db.add(
        ExtractionJob(
            dataset_id=ds.id,
            model_id=model.id,
            total=1,
            completed=1,
            status="completed",
        )
    )
    db.add(
        LiveEvalJob(
            dataset_id=ds.id,
            model_id=model.id,
            total=0,
            completed=0,
            status="completed",
        )
    )
    db.add(ModelTrainRecordLink(model_id=model.id, record_id=rec.id))
    db.commit()

    resp = client.delete(f"/api/v1/bioner/models/{model.id}")
    assert resp.status_code == 200
    assert db.get(Model, model.id) is None
    assert db.exec(select(ExtractionJob)).all() == []
    assert db.exec(select(LiveEvalJob)).all() == []
    assert db.exec(select(ModelTrainRecordLink)).all() == []


def test_delete_keeps_run_as_history(client, db, deleted_dirs):
    user_id = db.exec(select(User)).first().id
    ds = Dataset(name="ds", labels=["Drug"], user_id=user_id)
    db.add(ds)
    db.commit()
    model = _mk_model(db, source="trained")
    run = TrainingRun(
        dataset_id=ds.id,
        model_id=model.id,
        status="completed",
        base_model="base",
        labels=["Drug"],
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    resp = client.delete(f"/api/v1/bioner/models/{model.id}")
    assert resp.status_code == 200
    assert db.get(Model, model.id) is None
    kept = db.get(TrainingRun, run.id)
    assert kept is not None and kept.model_id is None


def test_delete_refuses_active_model(client, db, deleted_dirs):
    model = _mk_model(db)
    db.add(AppSettings(id=1, active_model_id=model.id))
    db.commit()
    resp = client.delete(f"/api/v1/bioner/models/{model.id}")
    assert resp.status_code == 409
    assert db.get(Model, model.id) is not None
    assert deleted_dirs == []


def test_delete_refuses_baseline_model(client, db, deleted_dirs):
    model = _mk_model(db, source="baseline")
    resp = client.delete(f"/api/v1/bioner/models/{model.id}")
    assert resp.status_code == 400
    assert db.get(Model, model.id) is not None


def test_delete_refuses_while_ner_job_active(client, db, deleted_dirs):
    user_id = db.exec(select(User)).first().id
    ds = Dataset(name="ds", labels=["Drug"], user_id=user_id)
    db.add(ds)
    db.commit()
    model = _mk_model(db)
    db.add(
        ExtractionJob(
            dataset_id=ds.id, model_id=model.id, total=5, completed=1, status="running"
        )
    )
    db.commit()
    resp = client.delete(f"/api/v1/bioner/models/{model.id}")
    assert resp.status_code == 409
    assert db.get(Model, model.id) is not None


def test_delete_missing_model_404(client, db, deleted_dirs):
    resp = client.delete("/api/v1/bioner/models/999")
    assert resp.status_code == 404


def test_delete_aborts_when_bioner_unreachable(client, db, monkeypatch):
    model = _mk_model(db)

    def _raise(dir_name):
        raise requests.ConnectionError("bioner down")

    monkeypatch.setattr(bioner_client, "delete_model_dir", _raise)
    resp = client.delete(f"/api/v1/bioner/models/{model.id}")
    assert resp.status_code == 503
    assert db.get(Model, model.id) is not None


def test_delete_skips_folder_for_non_local_path(client, db, deleted_dirs):
    """HF-id models have no local folder; only the DB row is removed."""
    model = _mk_model(db, path="E3-JSI/gliner-multi-med-ner-synthetic-v1")
    resp = client.delete(f"/api/v1/bioner/models/{model.id}")
    assert resp.status_code == 200
    assert db.get(Model, model.id) is None
    assert deleted_dirs == []
