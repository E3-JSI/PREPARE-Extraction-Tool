"""Shared pytest fixtures for backend unit/DB tests.

Uses an in-memory SQLite database so the model/service layer can be tested
without Postgres. Environment variables required by ``app.core.settings`` are
set here, before any ``app`` module is imported.
"""

import os

os.environ.setdefault("DATABASE_URL", "postgresql://u:p@localhost:5432/db")
os.environ.setdefault("ELASTICSEARCH_URL", "http://localhost:9200")
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")

from datetime import datetime, timezone

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.models_db import Dataset, Model, Record, User  # noqa: E402  (import after env setup)


@pytest.fixture
def session():
    """Yield a Session backed by a fresh in-memory SQLite database."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s
    SQLModel.metadata.drop_all(engine)


@pytest.fixture
def sample_user(session):
    """A persisted User."""
    user = User(username="tester", hashed_password="hashed")
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


@pytest.fixture
def sample_dataset(session, sample_user):
    """A persisted Dataset owned by ``sample_user``."""
    ds = Dataset(name="ds", labels=["Drug", "Diagnosis"], user_id=sample_user.id)
    session.add(ds)
    session.commit()
    session.refresh(ds)
    return ds


@pytest.fixture
def sample_record(session, sample_dataset):
    """A persisted Record in ``sample_dataset``."""
    rec = Record(
        patient_id="p1",
        visit_date=datetime.now(timezone.utc),
        text="aspirin 100mg",
        dataset_id=sample_dataset.id,
    )
    session.add(rec)
    session.commit()
    session.refresh(rec)
    return rec


@pytest.fixture
def sample_model(session, sample_dataset):
    """A persisted Model artifact."""
    model = Model(name="m", version="1", dataset_id=sample_dataset.id)
    session.add(model)
    session.commit()
    session.refresh(model)
    return model
