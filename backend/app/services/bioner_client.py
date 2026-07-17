from typing import Optional

import requests
from app.core.settings import settings


def get_training_status(run_id: int) -> Optional[dict]:
    """Return bioner's status snapshot for a run, or None if bioner doesn't know it.

    bioner's job manager is in-memory (and single-job), so a run it has never
    seen — or has forgotten after a restart — yields a 404, returned here as
    ``None`` (a definitive "not running"). A live run reports
    ``{"status": "running", ...}``.

    Raises ``requests.RequestException`` if bioner is unreachable — that is
    *unknown*, not "not running", so callers must not treat it as stale.
    """
    resp = requests.get(
        f"{settings.EXTRACT_HOST}/training/status/{run_id}",
        timeout=10,
    )
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json()


def get_available_models() -> dict:
    """Return bioner's scan of local model directories + launch engine/default.

    Shape: ``{current_engine, default_model, models_dir, models: [...]}``. Raises
    ``requests.RequestException`` if bioner is unreachable — callers treat that as
    "unknown" and must not mutate DB state on failure.
    """
    resp = requests.get(
        f"{settings.EXTRACT_HOST}/models/available",
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def activate_model(model_path: Optional[str]) -> None:
    """Hot-swap bioner's active NER model (``None`` reverts to its launch default).

    Raises ``requests.RequestException`` on connection errors or non-2xx
    responses (e.g. bioner's 400 INVALID_MODEL when the artifact is gone from
    disk) — callers outside a request handler must handle it themselves.
    """
    resp = requests.post(
        f"{settings.EXTRACT_HOST}/model/activate",
        json={"model": model_path},
        timeout=300,
    )
    resp.raise_for_status()


def delete_model_dir(dir_name: str) -> None:
    """Delete a local model folder from bioner's models dir.

    A 404 (folder already gone) is treated as success so deletion stays
    retryable after a partial failure. Raises ``requests.RequestException``
    on connection errors or other non-2xx responses (e.g. bioner's 409 when
    the folder backs its active or default model).
    """
    resp = requests.delete(
        f"{settings.EXTRACT_HOST}/models/{dir_name}",
        timeout=30,
    )
    if resp.status_code == 404:
        return
    resp.raise_for_status()


def http_error_detail(exc: Exception) -> Optional[str]:
    """bioner's structured error message from a ``requests.HTTPError``, if any.

    bioner errors carry ``{"detail": {"error": ..., "message": ...}}`` (or a
    plain-string detail); returns None when the exception has no such body.
    """
    response = getattr(exc, "response", None)
    if response is None:
        return None
    try:
        body = response.json()
    except ValueError:
        return None
    detail = body.get("detail") if isinstance(body, dict) else None
    if isinstance(detail, dict):
        return detail.get("message")
    if isinstance(detail, str):
        return detail
    return None


def start_training(payload: dict):
    response = requests.post(
        f"{settings.EXTRACT_HOST}/training/start",
        json=payload,
        timeout=30,
    )

    response.raise_for_status()

    return response.json()


def stop_training(run_id: int):
    response = requests.post(
        f"{settings.EXTRACT_HOST}/training/stop/{run_id}",
        timeout=10,
    )

    response.raise_for_status()

    return response.json()
