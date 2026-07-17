"""Tests for the "cluster all labels" background job.

Covers the job lifecycle (start guard, status, cancel), the per-label
skip-reviewed gate, and tolerance of labels with nothing to cluster.

Runs against in-memory SQLite. The embedding model and HDBSCAN are mocked so the
tests need no real models; ES is not touched (clustering does not use it).
"""

import os

os.environ.setdefault("DATABASE_URL", "postgresql://u:p@localhost:5432/db")
os.environ.setdefault("ELASTICSEARCH_URL", "http://localhost:9200")
os.environ.setdefault("SECRET_KEY", "test")
os.environ.setdefault("JWT_SECRET_KEY", "test")

from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import app.routes.v1.datasets as datasets
from app.models_db import (
    Cluster,
    ClusterJob,
    Dataset,
    Record,
    SourceTerm,
    User,
)


class _FakeEmbedder:
    """Deterministic embedding: identical texts → identical vectors."""

    def embed(self, texts):
        return [[float(hash(t) % 1000), 1.0] for t in texts]


class _FakeHDBSCAN:
    """Clusters identical embeddings together; nothing is treated as noise."""

    def __init__(self, **_kwargs):
        pass

    def fit_predict(self, embeddings):
        seen: dict = {}
        out = []
        nxt = 0
        for e in embeddings:
            key = tuple(e)
            if key not in seen:
                seen[key] = nxt
                nxt += 1
            out.append(seen[key])
        return out


@pytest.fixture
def engine(monkeypatch):
    """Fresh in-memory DB wired into the datasets module's module-level engine,
    with the embedding model + HDBSCAN mocked out."""
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(eng)
    monkeypatch.setattr(datasets, "engine", eng)
    monkeypatch.setattr(
        datasets.model_registry, "get_model", lambda _name: _FakeEmbedder()
    )
    monkeypatch.setattr(datasets, "HDBSCAN", _FakeHDBSCAN)
    yield eng
    SQLModel.metadata.drop_all(eng)


def _seed(engine, labels):
    with Session(engine) as s:
        user = User(username="t", hashed_password="h")
        s.add(user)
        s.commit()
        s.refresh(user)

        ds = Dataset(name="ds", labels=labels, user_id=user.id)
        s.add(ds)
        s.commit()
        s.refresh(ds)
        return ds.id, user.id


def _add_reviewed_terms(engine, dataset_id, label, values):
    """Add a reviewed record with source terms for a label."""
    with Session(engine) as s:
        rec = Record(
            patient_id="p",
            visit_date=datetime.now(timezone.utc),
            text="text",
            dataset_id=dataset_id,
            reviewed=True,
        )
        s.add(rec)
        s.commit()
        s.refresh(rec)
        for i, v in enumerate(values):
            s.add(
                SourceTerm(
                    record_id=rec.id,
                    value=v,
                    label=label,
                    start_position=i,
                    end_position=i + 1,
                    automatically_extracted=True,
                )
            )
        s.commit()


def test_cluster_all_clusters_unreviewed_and_skips_reviewed(engine):
    dataset_id, _user_id = _seed(engine, ["Drug", "Diagnosis"])
    _add_reviewed_terms(engine, dataset_id, "Drug", ["aspirin", "aspirin", "ibuprofen"])

    # Diagnosis already has a reviewed cluster → must be skipped, not wiped.
    with Session(engine) as s:
        reviewed_cluster = Cluster(
            dataset_id=dataset_id, label="Diagnosis", title="fever", reviewed=True
        )
        s.add(reviewed_cluster)
        s.commit()
        s.refresh(reviewed_cluster)
        preserved_cluster_id = reviewed_cluster.id

    with Session(engine) as s:
        job = ClusterJob(dataset_id=dataset_id, total=2, status="pending")
        s.add(job)
        s.commit()
        s.refresh(job)
        job_id = job.id

    datasets.run_cluster_all_job(job_id=job_id, dataset_id=dataset_id)

    with Session(engine) as s:
        job = s.get(ClusterJob, job_id)
        assert job.status == "completed"
        assert job.completed == 2
        assert job.clustered_labels == ["Drug"]
        assert job.skipped_labels == ["Diagnosis"]

        # Reviewed Diagnosis cluster preserved (not wiped).
        assert s.get(Cluster, preserved_cluster_id) is not None

        # Drug clusters were created.
        drug_clusters = s.exec(select(Cluster).where(Cluster.label == "Drug")).all()
        assert len(drug_clusters) >= 1


def test_cluster_all_tolerates_label_with_no_terms(engine):
    dataset_id, _user_id = _seed(engine, ["Empty"])

    with Session(engine) as s:
        job = ClusterJob(dataset_id=dataset_id, total=1, status="pending")
        s.add(job)
        s.commit()
        s.refresh(job)
        job_id = job.id

    datasets.run_cluster_all_job(job_id=job_id, dataset_id=dataset_id)

    with Session(engine) as s:
        job = s.get(ClusterJob, job_id)
        # Nothing to cluster is not a failure.
        assert job.status == "completed"
        assert job.completed == 1
        assert job.skipped_labels == []
        assert s.exec(select(Cluster).where(Cluster.label == "Empty")).all() == []


def test_cancelled_job_stops_before_processing(engine):
    dataset_id, _user_id = _seed(engine, ["Drug"])
    _add_reviewed_terms(engine, dataset_id, "Drug", ["aspirin", "aspirin"])

    with Session(engine) as s:
        job = ClusterJob(dataset_id=dataset_id, total=1, status="cancelled")
        s.add(job)
        s.commit()
        s.refresh(job)
        job_id = job.id

    datasets.run_cluster_all_job(job_id=job_id, dataset_id=dataset_id)

    with Session(engine) as s:
        job = s.get(ClusterJob, job_id)
        assert job.status == "cancelled"
        assert job.completed == 0
        # No clusters created — the job bailed out before processing.
        assert s.exec(select(Cluster)).all() == []


class _FakeBackgroundTasks:
    def __init__(self):
        self.tasks = []

    def add_task(self, func, **kwargs):
        self.tasks.append((func, kwargs))


def test_start_job_guards_against_active_job(engine):
    dataset_id, user_id = _seed(engine, ["Drug"])

    with Session(engine) as s:
        user = s.get(User, user_id)
        # An already-running job blocks a new start.
        s.add(ClusterJob(dataset_id=dataset_id, total=1, status="running"))
        s.commit()

        with pytest.raises(HTTPException) as exc:
            datasets.cluster_all_labels(
                dataset_id=dataset_id,
                background_tasks=_FakeBackgroundTasks(),
                current_user=user,
                db=s,
            )
        assert exc.value.status_code == 409


def test_start_job_queues_worker_and_status_reports(engine):
    dataset_id, user_id = _seed(engine, ["Drug", "Diagnosis"])

    with Session(engine) as s:
        user = s.get(User, user_id)
        tasks = _FakeBackgroundTasks()
        start = datasets.cluster_all_labels(
            dataset_id=dataset_id,
            background_tasks=tasks,
            current_user=user,
            db=s,
        )
        assert start.total == 2
        assert start.status == "pending"
        assert len(tasks.tasks) == 1

        status = datasets.get_cluster_job_status(
            dataset_id=dataset_id,
            job_id=start.job_id,
            current_user=user,
            db=s,
        )
        assert status.job_id == start.job_id
        assert status.total == 2

        cancel = datasets.cancel_cluster_job(
            dataset_id=dataset_id,
            job_id=start.job_id,
            current_user=user,
            db=s,
        )
        assert "Cancellation" in cancel.message

        job = s.get(ClusterJob, start.job_id)
        assert job.status == "cancelled"


def test_start_job_with_no_labels_completes_immediately(engine):
    dataset_id, user_id = _seed(engine, [])

    with Session(engine) as s:
        user = s.get(User, user_id)
        tasks = _FakeBackgroundTasks()
        start = datasets.cluster_all_labels(
            dataset_id=dataset_id,
            background_tasks=tasks,
            current_user=user,
            db=s,
        )
        assert start.status == "completed"
        assert start.total == 0
        # No worker scheduled when there is nothing to do.
        assert tasks.tasks == []
