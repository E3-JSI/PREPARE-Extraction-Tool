"""Tests for the validation exception handler.

Pydantic v2 puts the raw ``ValueError`` raised by a field validator into each
error's ``ctx``. Returning ``exc.errors()`` verbatim makes ``JSONResponse``
rendering blow up, which the generic handler turns into a 500. These tests pin
the 422 + human-readable message contract for both the ``RequestValidationError``
(route) path and the plain pydantic ``ValidationError`` path.
"""

import os

os.environ.setdefault("DATABASE_URL", "postgresql://u:p@localhost:5432/db")
os.environ.setdefault("ELASTICSEARCH_URL", "http://localhost:9200")
os.environ.setdefault("SECRET_KEY", "test")
os.environ.setdefault("JWT_SECRET_KEY", "test")

import asyncio
import json

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.core.database import get_session
from app.core.exceptions import validation_exception_handler
from app.main import app
from app.schemas import UserRegister

INVALID_USERNAME_MESSAGE = (
    "Username must contain only letters, numbers, and underscores"
)


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:

        def _get_session_override():
            yield session

        app.dependency_overrides[get_session] = _get_session_override
        yield TestClient(app)
        app.dependency_overrides.clear()


def test_register_invalid_username_returns_422(client):
    """A validator ValueError must surface as 422 with its message, never a 500."""
    response = client.post(
        "/api/v1/auth/register",
        json={"username": "claude-uitest", "password": "Valid-pass-1"},
    )

    assert response.status_code == 422
    body = response.json()
    assert body["detail"] == "Validation error"
    assert INVALID_USERNAME_MESSAGE in json.dumps(body["errors"])


def test_register_valid_username_succeeds(client):
    """Guard against the handler swallowing otherwise-valid registrations."""
    response = client.post(
        "/api/v1/auth/register",
        json={"username": "claude_uitest", "password": "Valid-pass-1"},
    )

    assert response.status_code == 201


def test_handler_renders_pydantic_validation_error():
    """The plain pydantic ValidationError path must render too (ctx holds a ValueError)."""
    with pytest.raises(ValidationError) as exc_info:
        UserRegister(username="claude-uitest", password="Valid-pass-1")

    request = Request({"type": "http", "method": "POST", "path": "/x", "headers": []})
    response = asyncio.run(validation_exception_handler(request, exc_info.value))

    assert response.status_code == 422
    body = json.loads(response.body)
    assert body["detail"] == "Validation error"
    assert INVALID_USERNAME_MESSAGE in json.dumps(body["errors"])
