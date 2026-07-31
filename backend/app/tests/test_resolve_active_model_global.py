"""Tests for resolve_active_model using the global active model."""

import os

os.environ.setdefault("DATABASE_URL", "postgresql://u:p@localhost:5432/db")
os.environ.setdefault("ELASTICSEARCH_URL", "http://localhost:9200")
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.models_db import Dataset, Model, User
from app.routes.v1.bioner import resolve_active_model
from app.services import training_service


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s
    SQLModel.metadata.drop_all(engine)


def _seed(db: Session):
    user = User(username="a", hashed_password="x")
    db.add(user)
    db.commit()
    db.refresh(user)

    ds = Dataset(name="d", labels=[], user_id=user.id)
    db.add(ds)
    db.commit()
    db.refresh(ds)

    m = Model(
        name="run-1",
        version="v",
        base_model="b",
        path="/models/run-1",
        dataset_id=ds.id,
    )
    db.add(m)
    db.commit()
    db.refresh(m)
    return m


def test_resolve_active_model_global_selection(db):
    """resolve_active_model returns model.id when a global model with a path is set.
    No bioner call should be made (model was already activated at selection time).
    """
    m = _seed(db)
    training_service.set_global_active_model(db, m.id)

    with patch("app.routes.v1.bioner.requests") as req:
        result = resolve_active_model(db)

    assert result == m.id
    # No HTTP calls: bioner was already activated at selection time
    req.post.assert_not_called()
    req.get.assert_not_called()


def test_resolve_active_model_uses_session_fixture(session, sample_model):
    """Works with the shared conftest session + sample_model fixtures."""
    sample_model.path = "/models/run-x"
    session.add(sample_model)
    session.commit()

    training_service.set_global_active_model(session, sample_model.id)

    with patch("app.routes.v1.bioner.requests") as req:
        result = resolve_active_model(session)

    assert result == sample_model.id
    req.post.assert_not_called()


def test_resolve_active_model_default_falls_back_to_bioner_info(db):
    """When no global model is set, resolve_active_model does a /model/info lookup."""
    # No AppSettings / active model set — ensure singleton is created as None
    settings_row = training_service.get_app_settings(db)
    assert settings_row.active_model_id is None

    mock_info_resp = MagicMock()
    mock_info_resp.raise_for_status = lambda: None
    mock_info_resp.json.return_value = {
        "model": {"name": "default-model", "version": "1"}
    }

    with patch("app.routes.v1.bioner.requests") as req:
        req.get.return_value = mock_info_resp
        result = resolve_active_model(db)

    req.get.assert_called_once()
    assert result is not None  # a Model row was created or retrieved
