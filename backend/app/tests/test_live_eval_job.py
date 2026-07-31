"""Tests for the live-eval background job.

The worker runs a trained model over a dataset's held-out reviewed records,
writes the model's predictions to ``SourceTermEx`` (never ``SourceTerm``), and
stores precision/recall/F1 metrics on the ``LiveEvalJob`` row. The NER HTTP call
and the bioner model hot-swap are mocked; runs against in-memory SQLite.
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

import app.routes.v1.live_eval as live_eval
from app.models_db import (
    AppSettings,
    Dataset,
    LiveEvalJob,
    Model,
    ModelTrainRecordLink,
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
    """Fresh in-memory DB wired into the live_eval module's module-level engine."""
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(eng)
    monkeypatch.setattr(live_eval, "engine", eng)
    yield eng
    SQLModel.metadata.drop_all(eng)


def _mk_record(s, ds_id, text, reviewed=True):
    r = Record(
        patient_id="p",
        visit_date=datetime.now(timezone.utc),
        text=text,
        dataset_id=ds_id,
        reviewed=reviewed,
    )
    s.add(r)
    s.commit()
    s.refresh(r)
    return r


def _gold(s, record_id, value, label, start, end):
    s.add(
        SourceTerm(
            record_id=record_id,
            value=value,
            label=label,
            start_position=start,
            end_position=end,
            automatically_extracted=False,
        )
    )
    s.commit()


def _seed(engine):
    """Dataset with a held-out reviewed record (gold), a trained record, an
    unreviewed record, and a reviewed record without gold offsets. Returns
    ids for the eval model, a previously-active model, and the held-out record.
    """
    with Session(engine) as s:
        user = User(username="t", hashed_password="h")
        s.add(user)
        s.commit()
        s.refresh(user)

        ds = Dataset(name="ds", labels=["Drug"], user_id=user.id)
        eval_model = Model(name="eval", version="1", path="/models/eval")
        prev_model = Model(name="prev", version="1", path="/models/prev")
        s.add(ds)
        s.add(eval_model)
        s.add(prev_model)
        s.commit()
        s.refresh(ds)
        s.refresh(eval_model)
        s.refresh(prev_model)

        # The globally-active model (must be restored after eval).
        s.add(AppSettings(id=1, active_model_id=prev_model.id))
        s.commit()

        # Held-out reviewed record with two gold Drug terms.
        heldout = _mk_record(s, ds.id, "aspirin and ibuprofen", reviewed=True)
        _gold(s, heldout.id, "aspirin", "Drug", 0, 7)
        _gold(s, heldout.id, "ibuprofen", "Drug", 12, 21)

        # Trained record (in the model's train_records) — must be excluded.
        trained = _mk_record(s, ds.id, "paracetamol", reviewed=True)
        _gold(s, trained.id, "paracetamol", "Drug", 0, 11)
        s.add(ModelTrainRecordLink(model_id=eval_model.id, record_id=trained.id))
        s.commit()

        # Unreviewed record — excluded.
        unreviewed = _mk_record(s, ds.id, "morphine", reviewed=False)
        _gold(s, unreviewed.id, "morphine", "Drug", 0, 8)

        # Reviewed but no gold offsets — excluded.
        no_gold = _mk_record(s, ds.id, "codeine", reviewed=True)

        return {
            "dataset_id": ds.id,
            "eval_model_id": eval_model.id,
            "prev_model_id": prev_model.id,
            "prev_path": prev_model.path,
            "heldout_id": heldout.id,
            "trained_id": trained.id,
            "unreviewed_id": unreviewed.id,
            "no_gold_id": no_gold.id,
        }


def _make_job(engine, dataset_id, model_id):
    with Session(engine) as s:
        job = LiveEvalJob(
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
        return job.id


def test_heldout_excludes_trained_unreviewed_and_ungolded(engine):
    ids = _seed(engine)
    with Session(engine) as s:
        heldout = live_eval._heldout_record_ids(s, ids["eval_model_id"], ids["dataset_id"])
    assert heldout == [ids["heldout_id"]]


def test_worker_writes_only_source_term_ex_and_computes_metrics(engine, monkeypatch):
    ids = _seed(engine)

    # NER predicts one correct term (aspirin) and one wrong term (tylenol),
    # missing ibuprofen: tp=1, fp=1, fn=1 -> precision=recall=f1=0.5.
    def fake_post(url, json=None, timeout=None):
        return _FakeResponse(
            [
                {"text": "aspirin", "label": "Drug", "start": 0, "end": 7, "score": 0.9},
                {"text": "tylenol", "label": "Drug", "start": 30, "end": 37, "score": 0.8},
            ]
        )

    activate_calls = []
    monkeypatch.setattr(live_eval.requests, "post", fake_post)
    monkeypatch.setattr(
        live_eval.bioner_client,
        "activate_model",
        lambda path: activate_calls.append(path),
    )

    job_id = _make_job(engine, ids["dataset_id"], ids["eval_model_id"])
    live_eval.run_live_eval_job(
        job_id=job_id,
        model_id=ids["eval_model_id"],
        dataset_id=ids["dataset_id"],
        labels=["Drug"],
    )

    with Session(engine) as s:
        job = s.get(LiveEvalJob, job_id)
        assert job.status == "completed"
        assert job.total == 1 and job.completed == 1

        # Metrics: per-label exact/relaxed/overlap + macro aggregate.
        m = job.metrics
        assert m["heldout_count"] == 1
        assert m["labels"] == ["Drug"]
        exact = m["per_label"]["Drug"]["exact"]
        assert exact["precision"] == pytest.approx(0.5)
        assert exact["recall"] == pytest.approx(0.5)
        assert exact["f1"] == pytest.approx(0.5)
        assert m["aggregate"]["exact"]["f1"] == pytest.approx(0.5)
        assert m["gold_entity_count"] == 2
        assert m["pred_entity_count"] == 2

        # Predictions written to SourceTermEx with the eval model_id, only for
        # the held-out record.
        ex = s.exec(select(SourceTermEx)).all()
        assert {e.value for e in ex} == {"aspirin", "tylenol"}
        assert all(e.model_id == ids["eval_model_id"] for e in ex)
        assert all(e.record_id == ids["heldout_id"] for e in ex)

        # SourceTerm (gold) is never written by live eval: still exactly the 4
        # gold terms seeded (2 held-out + trained + unreviewed).
        gold = s.exec(select(SourceTerm)).all()
        assert len(gold) == 4

    # bioner hot-swapped to the eval model path, then restored to the previously
    # active model path.
    assert activate_calls == ["/models/eval", ids["prev_path"]]


def test_worker_restores_active_model_on_ner_failure(engine, monkeypatch):
    ids = _seed(engine)

    class _Boom(live_eval.requests.RequestException):
        pass

    def fake_post(url, json=None, timeout=None):
        raise _Boom("bioner down")

    activate_calls = []
    monkeypatch.setattr(live_eval.requests, "post", fake_post)
    monkeypatch.setattr(
        live_eval.bioner_client,
        "activate_model",
        lambda path: activate_calls.append(path),
    )

    job_id = _make_job(engine, ids["dataset_id"], ids["eval_model_id"])
    live_eval.run_live_eval_job(
        job_id=job_id,
        model_id=ids["eval_model_id"],
        dataset_id=ids["dataset_id"],
        labels=["Drug"],
    )

    with Session(engine) as s:
        job = s.get(LiveEvalJob, job_id)
        assert job.status == "failed"
        assert job.error_message

    # Even on failure, the previously-active model is restored in the finally block.
    assert activate_calls == ["/models/eval", ids["prev_path"]]


class _FakeErrorResponse:
    """Minimal requests.Response stand-in carrying a JSON error body."""

    def __init__(self, payload, status_code=400):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


def test_worker_marks_job_failed_when_model_cannot_be_activated(engine, monkeypatch):
    """bioner rejecting the hot-swap (e.g. artifact deleted from disk -> 400
    INVALID_MODEL) must fail the job with bioner's message, not leave it running."""
    ids = _seed(engine)

    activate_calls = []

    def fake_activate(path):
        activate_calls.append(path)
        if len(activate_calls) == 1:
            raise live_eval.requests.HTTPError(
                "400 Client Error: Bad Request",
                response=_FakeErrorResponse(
                    {
                        "detail": {
                            "error": "INVALID_MODEL",
                            "message": "Model could not be found or loaded: /models/eval",
                        }
                    }
                ),
            )

    monkeypatch.setattr(live_eval.bioner_client, "activate_model", fake_activate)

    job_id = _make_job(engine, ids["dataset_id"], ids["eval_model_id"])
    live_eval.run_live_eval_job(
        job_id=job_id,
        model_id=ids["eval_model_id"],
        dataset_id=ids["dataset_id"],
        labels=["Drug"],
    )

    with Session(engine) as s:
        job = s.get(LiveEvalJob, job_id)
        assert job.status == "failed"
        assert "Model could not be found or loaded" in job.error_message

    # Activation failed, but the restore in the finally block still runs.
    assert activate_calls == ["/models/eval", ids["prev_path"]]


def test_worker_marks_job_failed_on_unexpected_error(engine, monkeypatch):
    """Regression: a non-requests exception used to escape the worker and leave
    the job stuck in 'running' forever (frontend polls a zombie job)."""
    ids = _seed(engine)

    def fake_activate(path):
        raise RuntimeError("boom")

    monkeypatch.setattr(live_eval.bioner_client, "activate_model", fake_activate)

    job_id = _make_job(engine, ids["dataset_id"], ids["eval_model_id"])
    live_eval.run_live_eval_job(
        job_id=job_id,
        model_id=ids["eval_model_id"],
        dataset_id=ids["dataset_id"],
        labels=["Drug"],
    )

    with Session(engine) as s:
        job = s.get(LiveEvalJob, job_id)
        assert job.status == "failed"
        assert "boom" in job.error_message


# ================================================
# /live-eval/start fail-fast (route-level)
# ================================================


@pytest.fixture
def client(engine):
    """TestClient over the seeded in-memory DB with auth/session overridden."""
    from app.core.database import get_session
    from app.main import app
    from app.routes.v1.auth import get_current_user

    ids = _seed(engine)
    with Session(engine) as session:
        user = session.exec(select(User)).first()

        def _get_session_override():
            yield session

        app.dependency_overrides[get_session] = _get_session_override
        app.dependency_overrides[get_current_user] = lambda: user
        c = TestClient(app)
        c.ids = ids
        yield c
        app.dependency_overrides.clear()


def _scan(paths):
    return {
        "current_engine": "gliner",
        "default_model": "/models/model",
        "models_dir": "/models",
        "models": [
            {
                "dir_name": p.rsplit("/", 1)[-1],
                "path": p,
                "engine": "gliner",
                "is_adapter": False,
                "name": p.rsplit("/", 1)[-1],
                "version": "1",
            }
            for p in paths
        ],
    }


def test_start_rejects_model_whose_artifact_is_gone(client, monkeypatch):
    """A Model row can outlive its on-disk folder; starting a live eval against
    it must 400 immediately instead of failing deep in the background worker."""
    monkeypatch.setattr(
        live_eval.bioner_client, "get_available_models", lambda: _scan(["/models/prev"])
    )
    resp = client.post(
        "/api/v1/bioner/live-eval/start",
        json={
            "model_id": client.ids["eval_model_id"],
            "dataset_id": client.ids["dataset_id"],
        },
    )
    assert resp.status_code == 400
    assert "no longer exists" in resp.json()["detail"]


def test_start_returns_503_when_bioner_scan_unreachable(client, monkeypatch):
    def _raise():
        raise live_eval.requests.ConnectionError("bioner down")

    monkeypatch.setattr(live_eval.bioner_client, "get_available_models", _raise)
    resp = client.post(
        "/api/v1/bioner/live-eval/start",
        json={
            "model_id": client.ids["eval_model_id"],
            "dataset_id": client.ids["dataset_id"],
        },
    )
    assert resp.status_code == 503


def test_start_accepts_model_with_existing_artifact(client, monkeypatch):
    monkeypatch.setattr(
        live_eval.bioner_client,
        "get_available_models",
        lambda: _scan(["/models/eval", "/models/prev"]),
    )
    worker_calls = []
    monkeypatch.setattr(live_eval, "run_live_eval_job", lambda **kw: worker_calls.append(kw))
    resp = client.post(
        "/api/v1/bioner/live-eval/start",
        json={
            "model_id": client.ids["eval_model_id"],
            "dataset_id": client.ids["dataset_id"],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "pending"
    assert body["total"] == 1
    assert len(worker_calls) == 1
