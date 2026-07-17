"""Tests for model discovery reconciliation (training_service.discover_models).

Covers the DB-side upsert/delete-missing policy and the fail-safe no-op on a
bioner scan error. The bioner HTTP call is mocked — no live bioner required.
"""

import requests
from sqlmodel import select

from app.models_db import Model
from app.services import training_service as svc


def _scan(
    models,
    *,
    current_engine="gliner",
    default_model="/models/base",
    models_dir="/models",
):
    return {
        "current_engine": current_engine,
        "default_model": default_model,
        "models_dir": models_dir,
        "models": models,
    }


def _entry(dir_name, engine="gliner", is_adapter=False, version="local"):
    return {
        "dir_name": dir_name,
        "path": f"/models/{dir_name}",
        "engine": engine,
        "is_adapter": is_adapter,
        "name": dir_name,
        "version": version,
    }


def test_model_table_has_source_and_engine_columns():
    cols = Model.__table__.columns
    assert "source" in cols
    assert "engine" in cols


def test_discover_upserts_new_folders(session, monkeypatch):
    monkeypatch.setattr(
        svc.bioner_client,
        "get_available_models",
        lambda: _scan(
            [_entry("m1"), _entry("adapter-x", engine="huggingface", is_adapter=True)]
        ),
    )
    meta = svc.discover_models(session)

    assert meta["ok"] is True
    assert meta["current_engine"] == "gliner"
    rows = {m.path: m for m in session.exec(select(Model)).all()}
    assert "/models/m1" in rows
    assert rows["/models/m1"].source == "discovered"
    assert rows["/models/m1"].engine == "gliner"
    assert rows["/models/adapter-x"].engine == "huggingface"


def test_discover_does_not_duplicate_existing_path(session, monkeypatch):
    session.add(
        Model(
            name="run-1",
            version="v",
            path="/models/m1",
            source="trained",
            engine="gliner",
        )
    )
    session.commit()
    monkeypatch.setattr(
        svc.bioner_client, "get_available_models", lambda: _scan([_entry("m1")])
    )
    svc.discover_models(session)

    rows = session.exec(select(Model).where(Model.path == "/models/m1")).all()
    assert len(rows) == 1
    assert rows[0].source == "trained"  # existing row untouched


def test_discover_fail_safe_no_op_on_scan_error(session, monkeypatch):
    session.add(
        Model(
            name="gone",
            version="v",
            path="/models/gone",
            source="discovered",
            engine="gliner",
        )
    )
    session.commit()

    def _boom():
        raise requests.RequestException("bioner down")

    monkeypatch.setattr(svc.bioner_client, "get_available_models", _boom)
    meta = svc.discover_models(session)

    assert meta["ok"] is False
    # No deletes despite the folder being "absent" — the scan never succeeded.
    assert (
        session.exec(select(Model).where(Model.path == "/models/gone")).first()
        is not None
    )


def test_discover_deletes_missing_only_in_models_dir(session, monkeypatch):
    # Under models dir, absent from scan -> deleted.
    session.add(
        Model(
            name="gone",
            version="v",
            path="/models/gone",
            source="discovered",
            engine="gliner",
        )
    )
    # path NULL anchor -> never deleted.
    session.add(
        Model(name="Base model", version="baseline", path=None, source="baseline")
    )
    # Outside the models dir -> never deleted.
    session.add(
        Model(
            name="ext",
            version="v",
            path="/other/ext",
            source="discovered",
            engine="gliner",
        )
    )
    session.commit()

    monkeypatch.setattr(
        svc.bioner_client, "get_available_models", lambda: _scan([_entry("kept")])
    )
    svc.discover_models(session)

    paths = {m.path for m in session.exec(select(Model)).all()}
    assert "/models/gone" not in paths  # deleted
    assert None in paths  # anchor kept
    assert "/other/ext" in paths  # outside dir kept
    assert "/models/kept" in paths  # newly discovered
