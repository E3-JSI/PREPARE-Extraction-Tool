"""Route test for POST /bioner/models/rescan (enriched reconciled list shape).

Runs against the real app with the DB session + current user overridden and the
bioner scan mocked, so no live bioner is required.
"""

import os

os.environ.setdefault("DATABASE_URL", "postgresql://u:p@localhost:5432/db")
os.environ.setdefault("ELASTICSEARCH_URL", "http://localhost:9200")
os.environ.setdefault("SECRET_KEY", "test")
os.environ.setdefault("JWT_SECRET_KEY", "test")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.core.database import get_session
from app.main import app
from app.models_db import User
from app.routes.v1.auth import get_current_user
from app.services import training_service as svc


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

        def _get_session_override():
            yield session

        app.dependency_overrides[get_session] = _get_session_override
        app.dependency_overrides[get_current_user] = lambda: user
        c = TestClient(app)
        c.session = session
        yield c
        app.dependency_overrides.clear()


def test_rescan_returns_enriched_shape(client, monkeypatch):
    scan = {
        "current_engine": "gliner",
        "default_model": "/models/base-model",
        "models_dir": "/models",
        "models": [
            {
                "dir_name": "run-1-20250101_120000",
                "path": "/models/run-1-20250101_120000",
                "engine": "gliner",
                "is_adapter": False,
                "name": "run-1-20250101_120000",
                "version": "20250101_120000",
            },
            {
                "dir_name": "llama-lora",
                "path": "/models/llama-lora",
                "engine": "huggingface",
                "is_adapter": True,
                "name": "llama-lora",
                "version": "local",
            },
        ],
    }
    monkeypatch.setattr(svc.bioner_client, "get_available_models", lambda: scan)

    resp = client.post("/api/v1/bioner/models/rescan")
    assert resp.status_code == 200
    body = resp.json()

    assert body["current_engine"] == "gliner"
    assert body["default_model"] == {"name": "base-model", "engine": "gliner"}

    by_name = {m["name"]: m for m in body["models"]}
    gliner = by_name["run-1-20250101_120000"]
    assert gliner["source"] == "discovered"
    assert gliner["engine"] == "gliner"
    assert gliner["is_adapter"] is False
    assert gliner["activatable"] is True  # engine matches, not an adapter

    adapter = by_name["llama-lora"]
    assert adapter["is_adapter"] is True
    assert adapter["activatable"] is False  # adapter -> not directly selectable


def test_rescan_no_op_when_bioner_unreachable(client, monkeypatch):
    import requests

    def _boom():
        raise requests.RequestException("down")

    monkeypatch.setattr(svc.bioner_client, "get_available_models", _boom)
    resp = client.post("/api/v1/bioner/models/rescan")
    assert resp.status_code == 200
    body = resp.json()
    assert body["current_engine"] is None
    assert body["default_model"] is None
    assert body["models"] == []
