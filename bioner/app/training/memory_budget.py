import ctypes
import gc
import os
import time
from pathlib import Path
from typing import Optional

from huggingface_hub import HfApi

from app.core.settings import settings

# Weights + gradients + AdamW moments is theoretically 4x the weight bytes;
# observed peaks run lower (~8 GB for gliner_multi-v2.1's 2.15 GB weights),
# so calibrated down to not refuse models that actually fit.
TRAINING_MEMORY_MULTIPLIER = 3.5

WEIGHT_SUFFIXES = (".safetensors", ".bin", ".pt")

_MIB = 1024**2
_GIB = 1024**3


class MemoryBudgetError(RuntimeError):
    """Fine-tune refused: the model won't fit in the available memory."""


def _weight_bytes_local(model_dir: str) -> Optional[int]:
    """Total bytes of weight files under a local model directory."""
    total = 0
    for root, _dirs, files in os.walk(model_dir):
        for name in files:
            if name.endswith(WEIGHT_SUFFIXES):
                total += (Path(root) / name).stat().st_size
    return total or None


def _weight_bytes_hub(repo_id: str) -> Optional[int]:
    """Total bytes of weight files in a HF-hub repo, or None if unknowable."""
    try:
        info = HfApi().model_info(repo_id, files_metadata=True)
    except Exception:
        # Hub unreachable / gated / bad id — from_pretrained surfaces the real error.
        return None
    total = sum(
        s.size
        for s in info.siblings or []
        if s.rfilename.endswith(WEIGHT_SUFFIXES) and s.size
    )
    return total or None


def _read_stat_value(stat_path: Path, key: str) -> int:
    try:
        for line in stat_path.read_text().splitlines():
            name, _, value = line.partition(" ")
            if name == key:
                return int(value)
    except (OSError, ValueError):
        pass
    return 0


def _cgroup_headroom(root: Path = Path("/sys/fs/cgroup")) -> Optional[int]:
    """Bytes left under the container's memory cap, or None when uncapped."""
    for limit_rel, used_rel, stat_rel, inactive_key in (
        ("memory.max", "memory.current", "memory.stat", "inactive_file"),
        (
            "memory/memory.limit_in_bytes",
            "memory/memory.usage_in_bytes",
            "memory/memory.stat",
            "total_inactive_file",
        ),
    ):
        try:
            limit = (root / limit_rel).read_text().strip()
            used = int((root / used_rel).read_text().strip())
        except (OSError, ValueError):
            continue
        # "max" (v2) or an absurdly large number (v1) means uncapped.
        if not limit.isdigit() or int(limit) >= 1 << 60:
            return None
        # Reclaimable page cache (e.g. cached model files) counts as "used"
        # in the cgroup but is dropped under pressure — don't hold it against
        # the budget.
        used -= _read_stat_value(root / stat_rel, inactive_key)
        return int(limit) - used
    return None


def available_memory_bytes() -> Optional[int]:
    """Memory this process can still claim: min(cgroup headroom, MemAvailable).

    None where neither is readable (e.g. non-Linux dev hosts) — callers treat
    that as "unknown, don't block".
    """
    candidates = []
    headroom = _cgroup_headroom()
    if headroom is not None:
        candidates.append(headroom)
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                candidates.append(int(line.split()[1]) * 1024)
                break
    except (OSError, ValueError):
        pass
    return min(candidates) if candidates else None


def release_freed_memory() -> None:
    """Return freed heap pages to the OS (glibc keeps them by default).

    Without this, a finished or stopped run leaves the worker's RSS inflated
    by gigabytes and the next run is refused for lack of memory. No-op where
    glibc isn't available.
    """
    gc.collect()
    try:
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except (OSError, AttributeError):
        pass


# A just-stopped run releases its memory over a few seconds; re-measure
# before refusing so an immediate rerun isn't rejected on transient state.
BUDGET_RECHECKS = 3
RECHECK_DELAY_SECONDS = 3.0


def check_memory_budget(base_model_path: str) -> None:
    """Raise MemoryBudgetError when the model likely can't be fine-tuned here.

    Skips silently (no raise) when either the weight size or the available
    memory can't be determined — an uncertain estimate must not block a run
    that might work.
    """
    weights = (
        _weight_bytes_local(base_model_path)
        if os.path.isdir(base_model_path)
        else _weight_bytes_hub(base_model_path)
    )
    if weights is None:
        return
    required = (
        weights * TRAINING_MEMORY_MULTIPLIER
        + settings.BIONER_TRAIN_OVERHEAD_MB * _MIB
    )

    available = None
    for attempt in range(BUDGET_RECHECKS):
        if attempt:
            time.sleep(RECHECK_DELAY_SECONDS)
        release_freed_memory()
        available = available_memory_bytes()
        if available is None or required <= available:
            return
    raise MemoryBudgetError(
        f"The base model '{base_model_path}' is too large to fine-tune on "
        f"this machine: training needs roughly {required / _GIB:.1f} GB of "
        f"memory, but only {available / _GIB:.1f} GB is available. Choose "
        f"a smaller base model, or increase the memory available to the "
        f"application."
    )


def ensure_memory_headroom() -> None:
    """Raise MemoryBudgetError when the machine is nearly out of memory.

    Called between training steps; no-op where memory can't be read. The
    watermark must exceed one step's transient allocation, or the OS
    OOM-kills the process before this can abort cleanly. A first low
    reading only triggers a trim + re-measure, so a transient dip (e.g.
    another service spiking) can't abort a run that would survive.
    """
    watermark = settings.BIONER_TRAIN_MIN_FREE_MB * _MIB
    available = available_memory_bytes()
    if available is None or available >= watermark:
        return
    release_freed_memory()
    available = available_memory_bytes()
    if available is None or available >= watermark:
        return
    raise MemoryBudgetError(
        f"Training aborted: the machine is nearly out of memory "
        f"({available / _GIB:.1f} GB left). This base model and batch size "
        f"need more memory than is available here. Try a smaller base model, "
        f"a lower batch size (under Advanced), or fewer training records — "
        f"or increase the memory available to the application."
    )
