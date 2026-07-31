"""Endpoint to switch the active NER model at runtime (activate / swap).

The model is validated and the desired state is persisted here (API process);
the in-memory engine is hot-swapped by the inference worker on its next request
(see ``NERAPI.predict`` / ``model_manager``).
"""

import logging
import os

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app import model_manager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Model"])

# Wired from main() once the server is built: lets the route validate against,
# and keep in sync, the same metadata that ``/model/info`` reports. ``engine`` is
# the launch engine (fixed for the process life) — model discovery is engine-aware.
_context: dict = {"server": None, "default_model": None, "engine": None}


def register_model_context(
    server, default_model: str, engine: str | None = None
) -> None:
    """Wire the LitServer, default model path, and launch engine into the routes."""
    _context["server"] = server
    _context["default_model"] = default_model
    _context["engine"] = engine


class ActivateModelRequest(BaseModel):
    """Body for ``POST /model/activate``. ``model=null`` reverts to the default."""

    model: str | None = None


@router.post("/model/activate")
def activate_model(request: ActivateModelRequest):
    """Switch the active NER model.

    Pass a model path / HuggingFace id to activate it, or ``null`` to revert to
    the default model the service started with. The target is validated here; on
    an invalid model the current model is left untouched and a 400 is returned.
    The in-memory engine is swapped by the inference worker on its next request.
    """
    default_model = _context["default_model"]
    target = request.model or default_model

    # The default model is already loaded and known-good — skip (network) checks.
    if target != default_model and not model_manager.validate_model(target):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "INVALID_MODEL",
                "message": f"Model could not be found or loaded: {target}",
            },
        )

    metadata = model_manager.read_model_metadata(target)
    model_manager.write_desired(target, metadata)

    # Keep ``/model/info`` consistent within this API process.
    server = _context["server"]
    if server is not None:
        server.model_metadata = metadata

    is_default = target == default_model
    logger.info(
        "Requested activation of NER model '%s' (default=%s)", target, is_default
    )
    return {"model": metadata, "active_model": target, "is_default": is_default}


@router.delete("/models/{dir_name}")
def delete_model_dir(dir_name: str):
    """Delete a local model directory under ``BIONER_MODELS_DIR``.

    Refuses to delete the launch-default model and the currently-active
    (desired) model — the worker could try to (re)load them at any moment.
    """
    models_dir = os.environ.get("BIONER_MODELS_DIR", "/models")
    target = os.path.join(models_dir, dir_name).rstrip("/")

    def _same(model: str | None) -> bool:
        return model is not None and model.rstrip("/") == target

    default_model = _context["default_model"]
    desired = model_manager.read_desired() or {}
    if _same(default_model) or _same(desired.get("model")):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "MODEL_IN_USE",
                "message": f"Model is the active or default model: {dir_name}",
            },
        )

    try:
        model_manager.remove_model_dir(models_dir, dir_name)
    except FileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "MODEL_NOT_FOUND",
                "message": f"No such model directory: {dir_name}",
            },
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "INVALID_MODEL_DIR", "message": str(exc)},
        )
    return {"deleted": dir_name}


@router.get("/models/available")
def list_available_models():
    """List local model directories under ``BIONER_MODELS_DIR`` with engine info.

    Engine detection is marker-based (see ``model_manager.detect_engine``). The
    launch ``current_engine`` and ``default_model`` are reported so the caller can
    tell which discovered models this process can actually activate (the engine is
    fixed at launch and cannot be hot-swapped across engine types).
    """
    models_dir = os.environ.get("BIONER_MODELS_DIR", "/models")
    return {
        "current_engine": _context["engine"],
        "default_model": _context["default_model"],
        "models_dir": models_dir,
        "models": model_manager.scan_models(models_dir),
    }
