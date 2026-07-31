"""Route tests for the training/monitoring endpoints under /bioner.

These run in Docker (the full app imports heavy ML deps). They use the FastAPI
TestClient against the real app with dependency overrides for the DB session
(in-memory SQLite) and the current user (a fake user).
"""

import os

os.environ.setdefault("DATABASE_URL", "postgresql://u:p@localhost:5432/db")
os.environ.setdefault("ELASTICSEARCH_URL", "http://localhost:9200")
os.environ.setdefault("SECRET_KEY", "test")
os.environ.setdefault("JWT_SECRET_KEY", "test")

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.core.database import get_session
from app.main import app
from app.models_db import Dataset, Record, TrainingMetric, TrainingRun, User
from app.routes.v1.auth import get_current_user


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        user = User(username="t", hashed_password="h")
        session.add(user)
        session.commit()
        session.refresh(user)

        ds = Dataset(name="ds", labels=["Drug"], user_id=user.id)
        session.add(ds)
        session.commit()
        session.refresh(ds)

        rec = Record(
            patient_id="p",
            visit_date=datetime.now(timezone.utc),
            text="aspirin",
            dataset_id=ds.id,
        )
        session.add(rec)
        session.commit()
        session.refresh(rec)

        def _get_session_override():
            yield session

        app.dependency_overrides[get_session] = _get_session_override
        app.dependency_overrides[get_current_user] = lambda: user
        c = TestClient(app)
        c.dataset_id = ds.id
        c.run_record_id = rec.id
        c.session = session
        yield c
        app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _no_trainer(monkeypatch):
    monkeypatch.setattr(
        "app.services.bioner_client.start_training", lambda *a, **k: None
    )
    monkeypatch.setattr(
        "app.services.bioner_client.stop_training", lambda *a, **k: None
    )


def test_start_creates_run(client):
    resp = client.post(
        "/api/v1/bioner/training/start",
        json={
            "dataset_id": client.dataset_id,
            "labels": ["Drug"],
            "base_model": "urchade/gliner_small-v2.1",
            "val_ratio": 0.1,
        },
    )
    assert resp.status_code == 200
    assert "run_id" in resp.json()


def test_full_stats_shape(client):
    resp = client.get(f"/api/v1/bioner/datasets/{client.dataset_id}/full-stats")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) >= {
        "totalRecords",
        "totalTerms",
        "labelDistribution",
        "reviewedRecords",
        "reviewedTerms",
        "reviewedLabelDistribution",
    }
    assert body["totalRecords"] >= 1


def test_full_stats_multi_shape(client):
    resp = client.post(
        "/api/v1/bioner/datasets/full-stats",
        json={"dataset_ids": [client.dataset_id]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) >= {
        "totalRecords",
        "totalTerms",
        "labelDistribution",
        "reviewedRecords",
        "reviewedTerms",
        "reviewedLabelDistribution",
    }
    assert body["totalRecords"] >= 1


def test_full_stats_scopes_reviewed_to_training_eligible(client):
    """reviewed_* counts only reviewed records + terms with valid offsets.

    The fixture dataset already has one unreviewed record with no terms. Add:
      - a reviewed record with two well-formed terms (Drug, Disease) and one
        term with null positions (excluded from the reviewed term count);
      - an unreviewed record with a well-formed term whose label (Symptom)
        exists ONLY in unreviewed data (→ 0 reviewed, 1 total).
    """
    from datetime import datetime, timezone

    from app.models_db import Record, SourceTerm

    db = client.session

    reviewed_rec = Record(
        patient_id="p2",
        visit_date=datetime.now(timezone.utc),
        text="aspirin and diabetes",
        dataset_id=client.dataset_id,
        reviewed=True,
    )
    unreviewed_rec = Record(
        patient_id="p3",
        visit_date=datetime.now(timezone.utc),
        text="cough",
        dataset_id=client.dataset_id,
        reviewed=False,
    )
    db.add(reviewed_rec)
    db.add(unreviewed_rec)
    db.commit()
    db.refresh(reviewed_rec)
    db.refresh(unreviewed_rec)

    db.add_all(
        [
            # Reviewed + valid offsets -> counted.
            SourceTerm(
                value="aspirin",
                label="Drug",
                start_position=0,
                end_position=7,
                record_id=reviewed_rec.id,
            ),
            SourceTerm(
                value="diabetes",
                label="Disease",
                start_position=12,
                end_position=20,
                record_id=reviewed_rec.id,
            ),
            # Reviewed but null offsets -> excluded from reviewed term count.
            SourceTerm(
                value="aspirin",
                label="Drug",
                start_position=None,
                end_position=None,
                record_id=reviewed_rec.id,
            ),
            # Unreviewed record -> excluded from all reviewed_* figures.
            SourceTerm(
                value="cough",
                label="Symptom",
                start_position=0,
                end_position=5,
                record_id=unreviewed_rec.id,
            ),
        ]
    )
    db.commit()

    resp = client.post(
        "/api/v1/bioner/datasets/full-stats",
        json={"dataset_ids": [client.dataset_id]},
    )
    assert resp.status_code == 200
    body = resp.json()

    # Totals: 3 records (fixture + 2), 4 terms, all labels present.
    assert body["totalRecords"] == 3
    assert body["totalTerms"] == 4
    assert body["labelDistribution"] == {"Drug": 2, "Disease": 1, "Symptom": 1}

    # Reviewed: only the reviewed record; its null-offset term is excluded.
    assert body["reviewedRecords"] == 1
    assert body["reviewedTerms"] == 2
    assert body["reviewedLabelDistribution"] == {"Drug": 1, "Disease": 1}
    # Symptom exists only in unreviewed data -> absent from reviewed dist.
    assert "Symptom" not in body["reviewedLabelDistribution"]


def test_start_multi_dataset_records_links(client):
    from app.models_db import Dataset
    from app.services import training_service

    db = client.session
    primary = db.get(Dataset, client.dataset_id)
    ds2 = Dataset(name="ds2", labels=["Drug"], user_id=primary.user_id)
    db.add(ds2)
    db.commit()
    db.refresh(ds2)

    resp = client.post(
        "/api/v1/bioner/training/start",
        json={
            "dataset_ids": [client.dataset_id, ds2.id],
            "labels": ["Drug"],
            "base_model": "urchade/gliner_small-v2.1",
            "val_ratio": 0.1,
        },
    )
    assert resp.status_code == 200
    run_id = resp.json()["run_id"]
    assert set(training_service.get_dataset_ids(db, run_id, role="train")) == {
        client.dataset_id,
        ds2.id,
    }


def test_start_rejects_unowned_dataset(client):
    resp = client.post(
        "/api/v1/bioner/training/start",
        json={
            "dataset_ids": [999999],
            "labels": ["Drug"],
            "base_model": "urchade/gliner_small-v2.1",
            "val_ratio": 0.1,
        },
    )
    assert resp.status_code == 404


def test_run_evaluation_shape(client):
    from app.services import training_service

    db = client.session
    run = training_service.create_run(
        db,
        dataset_ids=[client.dataset_id],
        base_model="b",
        labels=["Drug"],
        val_ratio=0.0,
    )
    training_service.record_evaluation(
        db, run.id, {"Drug": {"exact_f1": 0.8, "relaxed_f1": 0.9}}
    )
    resp = client.get(f"/api/v1/bioner/runs/{run.id}/evaluation")
    assert resp.status_code == 200
    assert resp.json()["per_label"]["Drug"]["exact_f1"] == 0.8


def test_start_rejects_empty_labels(client):
    resp = client.post(
        "/api/v1/bioner/training/start",
        json={
            "dataset_id": client.dataset_id,
            "labels": [],
            "base_model": "urchade/gliner_small-v2.1",
            "val_ratio": 0.1,
        },
    )
    assert resp.status_code == 422


def test_start_rejects_bad_val_ratio(client):
    resp = client.post(
        "/api/v1/bioner/training/start",
        json={
            "dataset_id": client.dataset_id,
            "labels": ["Drug"],
            "base_model": "urchade/gliner_small-v2.1",
            "val_ratio": 1.0,
        },
    )
    assert resp.status_code == 422


def test_start_rejects_concurrent_active_run(client):
    payload = {
        "dataset_id": client.dataset_id,
        "labels": ["Drug"],
        "base_model": "urchade/gliner_small-v2.1",
        "val_ratio": 0.1,
    }
    first = client.post("/api/v1/bioner/training/start", json=payload)
    assert first.status_code == 200
    second = client.post("/api/v1/bioner/training/start", json=payload)
    assert second.status_code == 409


def test_start_propagates_bioner_busy_409(client, monkeypatch):
    """A 409 from bioner is surfaced with its machine-readable reason code.

    Instead of silently marking the run failed and returning success, the proxy
    must return 409 with bioner's ``detail`` so the frontend can distinguish a
    genuinely-busy trainer from one that is still stopping (and retry).
    """
    import requests

    class _Resp:
        status_code = 409

        def json(self):
            return {
                "detail": {
                    "error": "TRAINING_STOPPING",
                    "message": "Previous training run is still stopping",
                    "suggestion": "Retry in a moment",
                }
            }

    def _raise(*args, **kwargs):
        raise requests.HTTPError(response=_Resp())

    monkeypatch.setattr("app.services.bioner_client.start_training", _raise)

    resp = client.post(
        "/api/v1/bioner/training/start",
        json={
            "dataset_id": client.dataset_id,
            "labels": ["Drug"],
            "base_model": "urchade/gliner_small-v2.1",
            "val_ratio": 0.1,
        },
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["error"] == "TRAINING_STOPPING"

    # The created run must not linger as active — it is marked failed so the
    # datasets aren't wedged.
    db = client.session
    runs = db.exec(select(TrainingRun)).all()
    assert runs and all(r.status == "failed" for r in runs)


def test_list_runs_paginated_and_enriched(client):
    from app.services import training_service

    db = client.session
    run = training_service.create_run(
        db,
        dataset_ids=[client.dataset_id],
        base_model="b",
        labels=["Drug"],
        val_ratio=0.2,
    )
    training_service.record_evaluation(
        db, run.id, {"Drug": {"exact_f1": 0.8}, "Dose": {"exact_f1": 0.6}}
    )
    resp = client.get(
        f"/api/v1/bioner/datasets/{client.dataset_id}/runs?page=1&limit=20"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "runs" in body and "pagination" in body
    assert body["pagination"]["total"] >= 1
    summary = next(r for r in body["runs"] if r["run_id"] == run.id)
    assert summary["base_model"] == "b"
    assert summary["labels"] == ["Drug"]
    assert summary["val_ratio"] == 0.2
    # macro-F1 = mean(0.8, 0.6)
    assert abs(summary["score"] - 0.7) < 1e-6


def test_rename_and_prefer_run(client):
    from app.services import training_service

    db = client.session
    run = training_service.create_run(
        db,
        dataset_ids=[client.dataset_id],
        base_model="b",
        labels=["Drug"],
        val_ratio=0.0,
    )
    resp = client.patch(
        f"/api/v1/bioner/runs/{run.id}",
        json={"name": "My best run", "preferred": True},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "My best run"
    assert body["preferred"] is True


def test_rename_run_syncs_linked_model_name(client):
    """Renaming a run must also rename its linked Model.

    The Models view displays ``Model.name``, but rename only wrote
    ``TrainingRun.name`` — so the rename appeared to do nothing. Assert the
    new name is what the /models list (the user-facing surface) reports.
    """
    from app.services import training_service

    db = client.session
    run = training_service.create_run(
        db,
        dataset_ids=[client.dataset_id],
        base_model="b",
        labels=["Drug"],
        val_ratio=0.0,
    )
    # A selectable trained model linked to the run (what the Models view lists).
    model = training_service._ensure_model(db, run)
    model.path = "/models/run-x"
    db.add(model)
    db.commit()
    assert model.name == f"run-{run.id}"

    resp = client.patch(
        f"/api/v1/bioner/runs/{run.id}",
        json={"name": "Aspirin detector"},
    )
    assert resp.status_code == 200

    listed = client.get("/api/v1/bioner/models").json()["models"]
    names = {m["id"]: m["name"] for m in listed}
    assert names[model.id] == "Aspirin detector"


def _make_trained_model(client, *, path="/models/run-x", dataset_id=None):
    """Persist a Model with an artifact path (a selectable trained model)."""
    from app.models_db import Model

    db = client.session
    model = Model(
        name="trained",
        version="1",
        base_model="b",
        path=path,
        dataset_id=dataset_id if dataset_id is not None else client.dataset_id,
    )
    db.add(model)
    db.commit()
    db.refresh(model)
    return model


def test_list_models_returns_trained(client):
    model = _make_trained_model(client)
    resp = client.get("/api/v1/bioner/models")
    assert resp.status_code == 200
    ids = [m["id"] for m in resp.json()["models"]]
    assert model.id in ids


def test_get_active_model_defaults_to_none(client):
    resp = client.get("/api/v1/bioner/active-model")
    assert resp.status_code == 200
    body = resp.json()
    assert "dataset_id" not in body
    assert body["active_model"] is None


def test_set_and_clear_active_model(client, monkeypatch):
    import app.routes.v1.bioner as bioner_routes

    monkeypatch.setattr(bioner_routes, "_activate_on_bioner", lambda *a, **k: None)

    model = _make_trained_model(client)
    # Set
    resp = client.post(
        "/api/v1/bioner/active-model",
        json={"model_id": model.id},
    )
    assert resp.status_code == 200
    assert resp.json()["active_model"]["id"] == model.id
    # Reflected by GET
    got = client.get("/api/v1/bioner/active-model")
    assert got.json()["active_model"]["id"] == model.id
    # Clear (null = default)
    cleared = client.post(
        "/api/v1/bioner/active-model",
        json={"model_id": None},
    )
    assert cleared.status_code == 200
    assert cleared.json()["active_model"] is None


def test_set_active_model_rejects_model_without_path(client):
    from app.models_db import Model

    db = client.session
    model = Model(name="m", version="1", dataset_id=client.dataset_id)
    db.add(model)
    db.commit()
    db.refresh(model)
    resp = client.post(
        "/api/v1/bioner/active-model",
        json={"model_id": model.id},
    )
    assert resp.status_code == 400


def test_set_active_model_rejects_missing_model(client):
    resp = client.post(
        "/api/v1/bioner/active-model",
        json={"model_id": 999999},
    )
    assert resp.status_code == 404


def test_set_active_model_blocked_during_extraction(client, monkeypatch):
    import app.routes.v1.bioner as bioner_routes

    monkeypatch.setattr(
        bioner_routes.extraction_lock, "any_extraction_job_active", lambda db: True
    )
    resp = client.post("/api/v1/bioner/active-model", json={"model_id": None})
    assert resp.status_code == 409


def test_delete_run(client):
    from app.services import training_service

    db = client.session
    run = training_service.create_run(
        db,
        dataset_ids=[client.dataset_id],
        base_model="b",
        labels=["Drug"],
        val_ratio=0.0,
    )
    resp = client.delete(f"/api/v1/bioner/runs/{run.id}")
    assert resp.status_code == 200
    follow = client.get(f"/api/v1/bioner/runs/{run.id}/evaluation")
    # evaluation endpoint still 200s but the run is gone; list no longer contains it
    listing = client.get(f"/api/v1/bioner/datasets/{client.dataset_id}/runs")
    assert all(r["run_id"] != run.id for r in listing.json()["runs"])
    assert follow.status_code == 200


def test_start_training_snapshots_train_stats(client):
    """After POST /training/start the created run carries a populated train_stats."""
    from app.models_db import TrainingRun

    resp = client.post(
        "/api/v1/bioner/training/start",
        json={
            "dataset_id": client.dataset_id,
            "labels": ["Drug"],
            "base_model": "urchade/gliner_small-v2.1",
            "val_ratio": 0.1,
        },
    )
    assert resp.status_code == 200
    run_id = resp.json()["run_id"]

    db = client.session
    db.expire_all()
    run = db.get(TrainingRun, run_id)
    assert run is not None
    assert run.train_stats is not None
    assert run.train_stats["record_count"] >= 1
    # The snapshot also carries the reviewed, training-eligible subset.
    assert "reviewed_record_count" in run.train_stats
    assert "reviewed_term_count" in run.train_stats
    assert "reviewed_label_distribution" in run.train_stats
    assert client.dataset_id in run.train_stats["train_dataset_ids"]


# ================================================
# Task 7: global model list + per-model detail
# ================================================


def _make_trained_model_with_run(client):
    """Create a TrainingRun + linked Model (with path + train_stats) for detail tests."""
    from app.models_db import Model
    from app.services import training_service

    db = client.session
    run = training_service.create_run(
        db,
        dataset_ids=[client.dataset_id],
        base_model="urchade/gliner_small-v2.1",
        labels=["Drug"],
        val_ratio=0.1,
        train_stats={"record_count": 1, "term_count": 0, "label_distribution": {}},
    )
    # Create Model linked to the run (mirrors complete_run without filesystem I/O)
    model = Model(
        name=f"run-{run.id}",
        version="20240101120000",
        base_model="urchade/gliner_small-v2.1",
        path=f"/models/run-{run.id}",
        dataset_id=client.dataset_id,
    )
    db.add(model)
    db.commit()
    db.refresh(model)
    run.model_id = model.id
    db.add(run)
    db.commit()
    db.refresh(run)
    db.refresh(model)
    return model, run


def test_models_list_excludes_baseline_rows_and_is_global(client):
    """GET /models returns trained models globally; 'Base model' rows are excluded."""
    from app.models_db import Model

    db = client.session

    # Create a trained model (has a path)
    trained, _ = _make_trained_model_with_run(client)

    # Create a baseline Model row (no path — same as get_baseline_model creates)
    baseline = Model(
        name="Base model",
        version="baseline",
        dataset_id=client.dataset_id,
    )
    db.add(baseline)
    db.commit()

    resp = client.get("/api/v1/bioner/models")
    assert resp.status_code == 200
    names = [m["name"] for m in resp.json()["models"]]

    assert "Base model" not in names
    assert trained.name in names


def test_models_list_marks_active(client, monkeypatch):
    """The model set as global active should have is_active == True in the list."""
    from app.services import training_service

    model = _make_trained_model(client)

    db = client.session
    training_service.set_global_active_model(db, model.id)

    resp = client.get("/api/v1/bioner/models")
    assert resp.status_code == 200
    summaries = resp.json()["models"]
    match = next(s for s in summaries if s["id"] == model.id)
    assert match["is_active"] is True


def test_model_detail_returns_train_stats_and_base_vs_trained(client):
    """GET /models/{id}/detail returns run info, train_stats, per_label keys."""
    model, run = _make_trained_model_with_run(client)

    resp = client.get(f"/api/v1/bioner/models/{model.id}/detail")
    assert resp.status_code == 200
    body = resp.json()

    assert body["model_id"] == model.id
    assert body["run_id"] == run.id
    assert "train_stats" in body
    assert "per_label_trained" in body
    assert "per_label_baseline" in body


def test_model_detail_404_for_unknown_model(client):
    """GET /models/99999/detail returns 404."""
    resp = client.get("/api/v1/bioner/models/99999/detail")
    assert resp.status_code == 404


# ================================================
# Task 9: step-indexed train/eval metrics + total_steps
# ================================================


def _make_pending_run(client):
    """Create a pending TrainingRun and return its id."""
    from app.models_db import TrainingRun

    db = client.session
    run = TrainingRun(
        dataset_id=client.dataset_id,
        base_model="m",
        labels=["Drug"],
        val_ratio=0.1,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run.id


def test_train_log_event_persists_step_metric(client):
    """POST train_log event with step → metrics endpoint returns a row with that step/loss."""
    run_id = _make_pending_run(client)
    payload = {
        "type": "train_log",
        "run_id": run_id,
        "step": 10,
        "epoch": 1.0,
        "loss": 0.5,
    }
    r = client.post("/api/v1/bioner/internal/training-events", json=payload)
    assert r.status_code == 200
    metrics = client.get(f"/api/v1/bioner/runs/{run_id}/metrics").json()
    assert any(m["step"] == 10 and m["loss"] == 0.5 for m in metrics)


def test_eval_step_persists_eval_loss(client):
    """POST train_log event with eval_loss → metrics endpoint returns a row with eval_loss."""
    run_id = _make_pending_run(client)
    payload = {
        "type": "train_log",
        "run_id": run_id,
        "step": 20,
        "epoch": 1.0,
        "eval_loss": 0.4,
    }
    client.post("/api/v1/bioner/internal/training-events", json=payload)
    metrics = client.get(f"/api/v1/bioner/runs/{run_id}/metrics").json()
    assert any(m["step"] == 20 and m["eval_loss"] == 0.4 for m in metrics)


def test_training_start_sets_total_steps(client):
    """POST training_start event with total_steps → run.train_stats["total_steps"] is set."""
    from app.models_db import TrainingRun

    run_id = _make_pending_run(client)
    payload = {
        "type": "training_start",
        "run_id": run_id,
        "num_epochs": 4,
        "total_steps": 200,
    }
    r = client.post("/api/v1/bioner/internal/training-events", json=payload)
    assert r.status_code == 200
    db = client.session
    db.expire_all()
    run = db.get(TrainingRun, run_id)
    assert run is not None
    assert run.train_stats is not None
    assert run.train_stats["total_steps"] == 200


def test_start_training_reconciles_stale_run(client, monkeypatch):
    """A 'running' run that bioner no longer tracks must not wedge new training."""
    from datetime import datetime, timedelta, timezone

    from app.services import training_service
    import app.services.bioner_client as bioner_client_mod
    from app.models_db import TrainingRun

    stale = training_service.create_run(
        client.session,
        dataset_ids=[client.dataset_id],
        base_model="urchade/gliner_multi-v2.1",
        labels=["Drug"],
        val_ratio=0.1,
    )
    training_service.mark_running(client.session, stale.id)
    # Age the run past the reconcile grace window (fresh runs are not probed).
    stale.created_at = datetime.now(timezone.utc) - timedelta(minutes=10)
    client.session.add(stale)
    client.session.commit()

    # bioner returns None (404 / unknown) -> the run is stale.
    monkeypatch.setattr(bioner_client_mod, "get_training_status", lambda run_id: None)

    resp = client.post(
        "/api/v1/bioner/training/start",
        json={
            "dataset_id": client.dataset_id,
            "labels": ["Drug"],
            "base_model": "urchade/gliner_multi-v2.1",
            "val_ratio": 0.1,
        },
    )
    assert resp.status_code == 200
    client.session.expire_all()
    assert client.session.get(TrainingRun, stale.id).status == "failed"


def test_start_training_blocks_genuinely_active_run(client, monkeypatch):
    """A run bioner confirms is still running must block a new run with 409."""
    from app.services import training_service
    import app.services.bioner_client as bioner_client_mod
    from app.models_db import TrainingRun

    active = training_service.create_run(
        client.session,
        dataset_ids=[client.dataset_id],
        base_model="urchade/gliner_multi-v2.1",
        labels=["Drug"],
        val_ratio=0.1,
    )
    training_service.mark_running(client.session, active.id)

    monkeypatch.setattr(
        bioner_client_mod, "get_training_status", lambda run_id: {"status": "running"}
    )

    resp = client.post(
        "/api/v1/bioner/training/start",
        json={
            "dataset_id": client.dataset_id,
            "labels": ["Drug"],
            "base_model": "urchade/gliner_multi-v2.1",
            "val_ratio": 0.1,
        },
    )
    assert resp.status_code == 409
    client.session.expire_all()
    assert client.session.get(TrainingRun, active.id).status == "running"


def test_active_run_null_when_idle(client):
    """GET /runs/active returns null (200) when no run is pending/running."""
    resp = client.get("/api/v1/bioner/runs/active")
    assert resp.status_code == 200
    assert resp.json() is None


def test_active_run_returns_inflight_progress(client):
    """A running run is returned with its steps, epoch bounds and loss curve so
    the Monitor page can rehydrate live progress in one call."""
    from app.services import training_service

    db = client.session
    run = training_service.create_run(
        db,
        dataset_ids=[client.dataset_id],
        base_model="urchade/gliner_small-v2.1",
        labels=["Drug"],
        val_ratio=0.1,
    )
    training_service.mark_running(db, run.id)
    training_service.set_total_steps(db, run.id, 200)
    training_service.set_num_epochs(db, run.id, 4)
    training_service.add_step_metric(db, run.id, step=10, epoch=1, loss=0.5)
    training_service.add_step_metric(db, run.id, step=20, epoch=1, loss=0.4)

    resp = client.get("/api/v1/bioner/runs/active")
    assert resp.status_code == 200
    body = resp.json()
    assert body is not None
    assert body["run_id"] == run.id
    assert body["status"] == "running"
    assert body["dataset_ids"] == [client.dataset_id]
    assert body["total_steps"] == 200
    assert body["current_step"] == 20
    assert body["num_epochs"] == 4
    assert body["current_epoch"] == 1
    assert len(body["metrics"]) == 2
    assert body["metrics"][0]["step"] == 10
    # Steps have been recorded, so the run is past the pre-training gap.
    assert body["phase"] == "training"


def test_active_run_derives_pretraining_phase(client):
    """The active-run endpoint derives the live pre-training phase from persisted
    state so the Monitor stepper can rehydrate mid-gap (before the first step)."""
    from app.services import training_service

    db = client.session
    run = training_service.create_run(
        db,
        dataset_ids=[client.dataset_id],
        base_model="urchade/gliner_small-v2.1",
        labels=["Drug"],
        val_ratio=0.1,
    )
    training_service.mark_running(db, run.id)

    def current_phase():
        resp = client.get("/api/v1/bioner/runs/active")
        assert resp.status_code == 200
        return resp.json()["phase"]

    # Nothing recorded yet: model is loading and data is being prepared.
    assert current_phase() == "loading"

    # training_start recorded total_steps → baseline evaluation is running.
    training_service.set_total_steps(db, run.id, 200)
    assert current_phase() == "baseline"

    # baseline evaluation stored → trainer is initializing.
    training_service.record_baseline_evaluation(db, run.id, {"Drug": {"exact_f1": 0.4}})
    assert current_phase() == "init"

    # first training step emitted → training.
    training_service.add_step_metric(db, run.id, step=1, epoch=1, loss=0.5)
    assert current_phase() == "training"


def test_active_run_hidden_from_other_user(client):
    """A run whose dataset belongs to another user is not surfaced."""
    from app.models_db import Dataset, User
    from app.services import training_service

    db = client.session
    other = User(username="other", hashed_password="h")
    db.add(other)
    db.commit()
    db.refresh(other)
    other_ds = Dataset(name="ods", labels=["Drug"], user_id=other.id)
    db.add(other_ds)
    db.commit()
    db.refresh(other_ds)

    run = training_service.create_run(
        db,
        dataset_ids=[other_ds.id],
        base_model="b",
        labels=["Drug"],
        val_ratio=0.1,
    )
    training_service.mark_running(db, run.id)

    resp = client.get("/api/v1/bioner/runs/active")
    assert resp.status_code == 200
    assert resp.json() is None


def test_epoch_update_not_persisted_but_train_log_is(client):
    """train_log is the single source of truth for the loss curve; the redundant
    epoch_update tick must not persist a duplicate (step-less) metric row."""
    db = client.session
    run = TrainingRun(
        dataset_id=client.dataset_id, base_model="m", labels=["Drug"], val_ratio=0.1
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    r1 = client.post(
        "/api/v1/bioner/internal/training-events",
        json={
            "type": "train_log",
            "run_id": run.id,
            "step": 1,
            "epoch": 0.5,
            "loss": 1.23,
        },
    )
    assert r1.status_code == 200

    r2 = client.post(
        "/api/v1/bioner/internal/training-events",
        json={"type": "epoch_update", "run_id": run.id, "epoch": 0.5, "loss": 1.23},
    )
    assert r2.status_code == 200

    rows = db.exec(select(TrainingMetric).where(TrainingMetric.run_id == run.id)).all()
    assert len(rows) == 1
    assert rows[0].step == 1
    assert rows[0].loss == 1.23
