"""Tests for the auto-map-all background job (bulk cluster → concept mapping).

Covers the job lifecycle mirrored from the extraction pattern: the start
endpoint queues a job, the worker transitions pending→running→completed while
ticking the per-cluster `completed` counter, already-mapped clusters are
skipped, cancellation stops the run, and the active/status endpoints report
progress.

Runs against in-memory SQLite; the Elasticsearch concept search is mocked.
"""

import os

os.environ.setdefault("DATABASE_URL", "postgresql://u:p@localhost:5432/db")
os.environ.setdefault("ELASTICSEARCH_URL", "http://localhost:9200")
os.environ.setdefault("SECRET_KEY", "test")
os.environ.setdefault("JWT_SECRET_KEY", "test")

from datetime import datetime

import pytest
from fastapi import BackgroundTasks, HTTPException
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import app.routes.v1.mappings as mappings
from app.models_db import (
    Cluster,
    Concept,
    Dataset,
    MappingJob,
    SourceToConceptMap,
    User,
    Vocabulary,
)
from app.schemas import AutoMapAllRequest


@pytest.fixture
def engine(monkeypatch):
    """Fresh in-memory DB, wired into the mappings module's module-level engine."""
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(eng)
    # The background worker opens its own Session(engine) from this module global.
    monkeypatch.setattr(mappings, "engine", eng)
    yield eng
    SQLModel.metadata.drop_all(eng)


def _seed(engine, *, already_mapped=False):
    """Dataset with reviewed clusters plus one unreviewed cluster (never processed).

    Returns (user_id, dataset_id, reviewed_cluster_ids, concept_id).
    """
    with Session(engine) as s:
        user = User(username="t", hashed_password="h")
        s.add(user)
        s.commit()
        s.refresh(user)

        ds = Dataset(name="ds", labels=["Drug"], user_id=user.id)
        vocab = Vocabulary(name="v", user_id=user.id)
        s.add(ds)
        s.add(vocab)
        s.commit()
        s.refresh(ds)
        s.refresh(vocab)

        concept = Concept(
            vocab_term_id="C1",
            vocab_term_name="Aspirin",
            domain_id="Drug",
            concept_class_id="Ingredient",
            standard_concept="S",
            concept_code="123",
            valid_start_date=datetime(1970, 1, 1),
            valid_end_date=datetime(2099, 12, 31),
            invalid_reason=None,
            vocabulary_id=vocab.id,
        )
        s.add(concept)
        s.commit()
        s.refresh(concept)

        def mk_cluster(title, reviewed=True, label="Drug"):
            c = Cluster(label=label, title=title, reviewed=reviewed, dataset_id=ds.id)
            s.add(c)
            s.commit()
            s.refresh(c)
            return c

        c1 = mk_cluster("aspirin")
        c2 = mk_cluster("ibuprofen")
        mk_cluster("unreviewed", reviewed=False)  # excluded from the run

        if already_mapped:
            s.add(
                SourceToConceptMap(
                    cluster_id=c1.id, concept_id=concept.id, status="approved"
                )
            )
            s.commit()

        return user.id, ds.id, [c1.id, c2.id], concept.id


def _make_job(engine, dataset_id, total):
    with Session(engine) as s:
        job = MappingJob(
            dataset_id=dataset_id, total=total, completed=0, status="pending"
        )
        s.add(job)
        s.commit()
        s.refresh(job)
        return job.id


def _fake_search(concept_id):
    """Return a search_concepts_* stand-in that always yields concept_id."""

    def _search(query_text, vocab_ids, limit):
        return [{"concept_id": concept_id}], None

    return _search


def test_worker_maps_reviewed_clusters_and_completes(engine, monkeypatch):
    _, dataset_id, cluster_ids, concept_id = _seed(engine)
    monkeypatch.setattr(
        mappings.indexer, "search_concepts_vector", _fake_search(concept_id)
    )

    job_id = _make_job(engine, dataset_id, total=len(cluster_ids))
    mappings.run_auto_map_all_job(
        job_id=job_id,
        dataset_id=dataset_id,
        vocabulary_ids=[1],
        label=None,
        use_cluster_terms=False,
        search_type="vector",
    )

    with Session(engine) as s:
        job = s.get(MappingJob, job_id)
        assert job.status == "completed"
        assert job.completed == 2  # both reviewed clusters ticked
        assert job.mapped_count == 2
        assert job.failed_count == 0
        # Unreviewed cluster is never mapped.
        mapped_cluster_ids = {
            m.cluster_id for m in s.exec(select(SourceToConceptMap)).all()
        }
        assert mapped_cluster_ids == set(cluster_ids)


def test_worker_skips_already_mapped_clusters(engine, monkeypatch):
    _, dataset_id, cluster_ids, concept_id = _seed(engine, already_mapped=True)
    monkeypatch.setattr(
        mappings.indexer, "search_concepts_vector", _fake_search(concept_id)
    )

    job_id = _make_job(engine, dataset_id, total=len(cluster_ids))
    mappings.run_auto_map_all_job(
        job_id=job_id,
        dataset_id=dataset_id,
        vocabulary_ids=[1],
        label=None,
        use_cluster_terms=False,
        search_type="vector",
    )

    with Session(engine) as s:
        job = s.get(MappingJob, job_id)
        assert job.status == "completed"
        # Both reviewed clusters count toward completed (mapped + skipped).
        assert job.completed == 2
        # Only the previously-unmapped cluster gets a new mapping.
        assert job.mapped_count == 1
        # The already-mapped cluster keeps its single mapping (no duplicate).
        maps = s.exec(
            select(SourceToConceptMap).where(
                SourceToConceptMap.cluster_id == cluster_ids[0]
            )
        ).all()
        assert len(maps) == 1


def test_worker_counts_failures_when_no_match(engine, monkeypatch):
    _, dataset_id, cluster_ids, _ = _seed(engine)

    def _no_results(query_text, vocab_ids, limit):
        return [], None

    monkeypatch.setattr(mappings.indexer, "search_concepts_vector", _no_results)

    job_id = _make_job(engine, dataset_id, total=len(cluster_ids))
    mappings.run_auto_map_all_job(
        job_id=job_id,
        dataset_id=dataset_id,
        vocabulary_ids=[1],
        label=None,
        use_cluster_terms=False,
        search_type="vector",
    )

    with Session(engine) as s:
        job = s.get(MappingJob, job_id)
        assert job.status == "completed"
        assert job.completed == 2
        assert job.mapped_count == 0
        assert job.failed_count == 2
        assert s.exec(select(SourceToConceptMap)).all() == []


def test_worker_returns_early_when_cancelled(engine, monkeypatch):
    _, dataset_id, cluster_ids, concept_id = _seed(engine)
    monkeypatch.setattr(
        mappings.indexer, "search_concepts_vector", _fake_search(concept_id)
    )

    job_id = _make_job(engine, dataset_id, total=len(cluster_ids))
    with Session(engine) as s:
        job = s.get(MappingJob, job_id)
        job.status = "cancelled"
        s.add(job)
        s.commit()

    mappings.run_auto_map_all_job(
        job_id=job_id,
        dataset_id=dataset_id,
        vocabulary_ids=[1],
        label=None,
        use_cluster_terms=False,
        search_type="vector",
    )

    with Session(engine) as s:
        job = s.get(MappingJob, job_id)
        assert job.status == "cancelled"
        assert job.completed == 0
        assert s.exec(select(SourceToConceptMap)).all() == []


def test_worker_stops_mid_run_on_cancel(engine, monkeypatch):
    """A cancel requested during the run stops before the next cluster."""
    _, dataset_id, cluster_ids, concept_id = _seed(engine)

    job_holder = {}

    def _search_then_cancel(query_text, vocab_ids, limit):
        # After the first cluster is searched, flip the job to cancelled so the
        # loop's per-iteration check breaks before the second cluster.
        with Session(engine) as s:
            job = s.get(MappingJob, job_holder["id"])
            job.status = "cancelled"
            s.add(job)
            s.commit()
        return [{"concept_id": concept_id}], None

    monkeypatch.setattr(mappings.indexer, "search_concepts_vector", _search_then_cancel)

    job_id = _make_job(engine, dataset_id, total=len(cluster_ids))
    job_holder["id"] = job_id
    mappings.run_auto_map_all_job(
        job_id=job_id,
        dataset_id=dataset_id,
        vocabulary_ids=[1],
        label=None,
        use_cluster_terms=False,
        search_type="vector",
    )

    with Session(engine) as s:
        job = s.get(MappingJob, job_id)
        assert job.status == "cancelled"
        # First cluster processed and committed; second cluster skipped.
        assert job.completed == 1
        assert len(s.exec(select(SourceToConceptMap)).all()) == 1


def test_start_endpoint_queues_job_and_reports_total(engine):
    user_id, dataset_id, cluster_ids, _ = _seed(engine)
    with Session(engine) as s:
        user = s.get(User, user_id)
        bt = BackgroundTasks()
        resp = mappings.auto_map_all_clusters(
            dataset_id=dataset_id,
            request=AutoMapAllRequest(vocabulary_ids=[1]),
            background_tasks=bt,
            current_user=user,
            db=s,
        )

        assert resp.status == "pending"
        assert resp.total == 2  # two reviewed clusters
        assert resp.job_id is not None
        assert len(bt.tasks) == 1  # worker enqueued

        job = s.get(MappingJob, resp.job_id)
        assert job is not None and job.status == "pending"


def test_start_endpoint_conflicts_with_active_job(engine):
    user_id, dataset_id, _, _ = _seed(engine)
    with Session(engine) as s:
        user = s.get(User, user_id)
        s.add(MappingJob(dataset_id=dataset_id, total=2, status="running"))
        s.commit()

        with pytest.raises(HTTPException) as exc:
            mappings.auto_map_all_clusters(
                dataset_id=dataset_id,
                request=AutoMapAllRequest(vocabulary_ids=[1]),
                background_tasks=BackgroundTasks(),
                current_user=user,
                db=s,
            )
        assert exc.value.status_code == 409
        assert "already running" in exc.value.detail


def test_active_and_status_endpoints_report_progress(engine):
    user_id, dataset_id, _, _ = _seed(engine)
    with Session(engine) as s:
        user = s.get(User, user_id)
        job = MappingJob(
            dataset_id=dataset_id,
            total=2,
            completed=1,
            mapped_count=1,
            status="running",
        )
        s.add(job)
        s.commit()
        s.refresh(job)

        active = mappings.get_active_auto_map_job(
            dataset_id=dataset_id, current_user=user, db=s
        )
        assert active is not None
        assert active.job_id == job.id
        assert active.completed == 1
        assert active.total == 2
        assert active.mapped_count == 1
        assert active.status == "running"

        status_resp = mappings.get_auto_map_job_status(
            dataset_id=dataset_id, job_id=job.id, current_user=user, db=s
        )
        assert status_resp.job_id == job.id
        assert status_resp.status == "running"


def test_cancel_endpoint_marks_job_cancelled(engine):
    user_id, dataset_id, _, _ = _seed(engine)
    with Session(engine) as s:
        user = s.get(User, user_id)
        job = MappingJob(dataset_id=dataset_id, total=2, status="running")
        s.add(job)
        s.commit()
        s.refresh(job)

        mappings.cancel_auto_map_job(
            dataset_id=dataset_id, job_id=job.id, current_user=user, db=s
        )
        s.refresh(job)
        assert job.status == "cancelled"


def test_start_endpoint_completes_immediately_when_no_clusters(engine):
    """No reviewed clusters → job short-circuits to completed, no worker task."""
    with Session(engine) as s:
        user = User(username="u", hashed_password="h")
        s.add(user)
        s.commit()
        s.refresh(user)
        ds = Dataset(name="empty", labels=["Drug"], user_id=user.id)
        s.add(ds)
        s.commit()
        s.refresh(ds)

        bt = BackgroundTasks()
        resp = mappings.auto_map_all_clusters(
            dataset_id=ds.id,
            request=AutoMapAllRequest(vocabulary_ids=[1]),
            background_tasks=bt,
            current_user=user,
            db=s,
        )
        assert resp.status == "completed"
        assert resp.total == 0
        assert len(bt.tasks) == 0
