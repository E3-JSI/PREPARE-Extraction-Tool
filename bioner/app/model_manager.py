"""Active-model state shared between the API process and the inference worker.

LitServe runs ``LitAPI.setup``/``predict`` in a separate (spawned) worker
process, while HTTP route handlers (``/model/activate``, ``/model/info``) run in
the API process. They therefore cannot share the loaded model in memory. This
module persists the *desired* active model to a small JSON state file: the
activate route writes it, and the worker reads it before each inference and
hot-swaps the in-memory engine when it changes (see ``NERAPI.predict``).
"""

import json
import logging
import os
import re
import shutil
import tempfile
from pathlib import Path

from huggingface_hub import model_info

logger = logging.getLogger(__name__)

# Shared state file. Defaults to a temp path so it resets on a fresh container;
# override with BIONER_ACTIVE_MODEL_STATE when the API and worker need a
# specific shared location.
STATE_PATH = Path(
    os.environ.get("BIONER_ACTIVE_MODEL_STATE")
    or (Path(tempfile.gettempdir()) / "bioner_active_model.json")
)


def read_model_metadata(model_dir: str) -> dict:
    """Return a model's ``metadata.json`` (name/version), or sensible defaults.

    A local model directory may ship a ``metadata.json``; HuggingFace ids and
    directories without one fall back to a generic name/version.
    """
    metadata_path = Path(model_dir) / "metadata.json"
    if not metadata_path.exists():
        return {"name": "Extraction model", "version": "1.0"}
    with open(metadata_path, "r", encoding="utf-8") as f:
        metadata = json.load(f)
    if "name" not in metadata or "version" not in metadata:
        raise ValueError("metadata.json must contain at least 'name' and 'version'")
    return metadata


def is_local_path(model: str) -> bool:
    """True if ``model`` points at an existing local file/directory."""
    try:
        return Path(model).exists()
    except OSError:
        return False


def validate_model(model: str) -> bool:
    """Best-effort check that a model can be loaded.

    Local paths must exist; otherwise the id is validated against the
    HuggingFace hub. Network validation is skipped for local paths so offline
    activation of locally trained models keeps working.
    """
    if is_local_path(model):
        return True
    try:
        model_info(model)
        return True
    except Exception:
        return False


def write_desired(model: str, metadata: dict) -> None:
    """Atomically record the desired active model for the worker to pick up."""
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_name(STATE_PATH.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"model": model, "metadata": metadata}, f)
    os.replace(tmp, STATE_PATH)


def read_desired() -> dict | None:
    """Return the desired-model state written by the activate route, if any."""
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


# ---------------------------------------------------------------------------
# On-disk model discovery
# ---------------------------------------------------------------------------

# Matches trained-run output folders `run-<id>-<YYYYMMDD_HHMMSS>` so a version
# can be derived from the timestamp when no metadata.json is present.
_RUN_DIR_RE = re.compile(r"^run-\d+-(\d{8}_\d{6})$")


def detect_engine(model_dir: Path) -> tuple[str | None, bool]:
    """Infer the engine backing a local model directory from marker files.

    Returns ``(engine, is_adapter)``. ``engine`` is ``None`` when the directory
    is not a recognizable model — the caller should skip it silently. Order
    matters: an adapter folder may also ship a transformers ``config.json``, so
    the adapter marker is checked before the plain huggingface marker.
    """
    if (model_dir / "gliner_config.json").exists():
        return "gliner", False
    if (model_dir / "adapter_config.json").exists():
        return "huggingface", True
    if (model_dir / "config.json").exists():
        return "huggingface", False
    return None, False


def _derive_name_version(model_dir: Path) -> tuple[str, str]:
    """Best-effort display name/version for a local model directory.

    Prefers a shipped ``metadata.json``; otherwise falls back to the folder name
    and derives the version from a ``run-<id>-<ts>`` timestamp, else ``"local"``.
    """
    if (model_dir / "metadata.json").exists():
        metadata = read_model_metadata(str(model_dir))
        return metadata.get("name") or model_dir.name, str(
            metadata.get("version") or "local"
        )
    match = _RUN_DIR_RE.match(model_dir.name)
    version = match.group(1) if match else "local"
    return model_dir.name, version


def remove_model_dir(models_dir: str, dir_name: str) -> None:
    """Delete a model directory under ``models_dir``.

    ``dir_name`` must be a bare directory name (no separators or dot-refs) and
    the directory must carry an engine marker file (see ``detect_engine``), so
    this can never remove anything but an immediate model folder. Raises
    ``ValueError`` on an invalid name / non-model dir, ``FileNotFoundError``
    when the directory does not exist.
    """
    if not dir_name or dir_name != Path(dir_name).name or dir_name in {".", ".."}:
        raise ValueError(f"Invalid model directory name: {dir_name!r}")
    target = Path(models_dir) / dir_name
    if not target.is_dir():
        raise FileNotFoundError(f"No such model directory: {dir_name}")
    engine, _ = detect_engine(target)
    if engine is None:
        raise ValueError(f"Not a model directory: {dir_name}")
    shutil.rmtree(target)
    logger.info("Removed model directory %s", target)


def scan_models(models_dir: str) -> list[dict]:
    """Scan ``models_dir`` for local model directories and describe each one.

    Only immediate subdirectories are considered; anything without an engine
    marker file (dotfiles, ``.cache``, junk) is skipped. Each entry is
    ``{dir_name, path, engine, is_adapter, name, version}``.
    """
    base = Path(models_dir)
    models: list[dict] = []
    if not base.is_dir():
        return models
    for sub in sorted(base.iterdir()):
        if not sub.is_dir():
            continue
        engine, is_adapter = detect_engine(sub)
        if engine is None:
            continue
        name, version = _derive_name_version(sub)
        models.append(
            {
                "dir_name": sub.name,
                "path": str(sub),
                "engine": engine,
                "is_adapter": is_adapter,
                "name": name,
                "version": version,
            }
        )
    return models
