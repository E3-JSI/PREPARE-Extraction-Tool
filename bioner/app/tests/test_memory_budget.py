import pytest

from app.training import memory_budget
from app.training.memory_budget import (
    MemoryBudgetError,
    _cgroup_headroom,
    _weight_bytes_local,
    check_memory_budget,
    ensure_memory_headroom,
    release_freed_memory,
)

GIB = 1024**3


def test_local_weight_files_are_summed(tmp_path):
    (tmp_path / "model.safetensors").write_bytes(b"x" * 1000)
    (tmp_path / "pytorch_model.bin").write_bytes(b"x" * 500)
    (tmp_path / "config.json").write_bytes(b"x" * 9999)  # not a weight file
    assert _weight_bytes_local(str(tmp_path)) == 1500


def test_local_dir_without_weights_is_unknown(tmp_path):
    (tmp_path / "config.json").write_bytes(b"{}")
    assert _weight_bytes_local(str(tmp_path)) is None


def test_oversized_model_is_refused(monkeypatch):
    # ~5 GB of weights -> ~18.5 GB needed; only 8 GB available.
    monkeypatch.setattr(memory_budget, "_weight_bytes_hub", lambda repo: 5 * GIB)
    monkeypatch.setattr(memory_budget, "available_memory_bytes", lambda: 8 * GIB)
    monkeypatch.setattr(memory_budget, "RECHECK_DELAY_SECONDS", 0)
    with pytest.raises(MemoryBudgetError, match="too large to fine-tune"):
        check_memory_budget("some/xxl-model")


def test_fitting_model_passes(monkeypatch):
    # ~1.2 GB of weights -> ~6.8 GB needed; 12 GB available.
    monkeypatch.setattr(memory_budget, "_weight_bytes_hub", lambda repo: int(1.2 * GIB))
    monkeypatch.setattr(memory_budget, "available_memory_bytes", lambda: 12 * GIB)
    check_memory_budget("some/large-model")


def test_unknown_size_or_budget_never_blocks(monkeypatch):
    monkeypatch.setattr(memory_budget, "_weight_bytes_hub", lambda repo: None)
    monkeypatch.setattr(memory_budget, "available_memory_bytes", lambda: 8 * GIB)
    check_memory_budget("unknown/model")

    monkeypatch.setattr(memory_budget, "_weight_bytes_hub", lambda repo: 5 * GIB)
    monkeypatch.setattr(memory_budget, "available_memory_bytes", lambda: None)
    check_memory_budget("unknown/host")


def test_headroom_guard_aborts_when_memory_is_nearly_gone(monkeypatch):
    monkeypatch.setattr(
        memory_budget, "available_memory_bytes", lambda: int(0.4 * GIB)
    )
    with pytest.raises(MemoryBudgetError, match="nearly out of memory"):
        ensure_memory_headroom()


def test_headroom_guard_survives_a_transient_dip(monkeypatch):
    # First reading low, second (after trim + re-measure) fine -> no abort.
    readings = iter([int(0.4 * GIB), 4 * GIB])
    monkeypatch.setattr(
        memory_budget, "available_memory_bytes", lambda: next(readings)
    )
    ensure_memory_headroom()


def test_headroom_guard_passes_with_room_or_unknown(monkeypatch):
    monkeypatch.setattr(memory_budget, "available_memory_bytes", lambda: 4 * GIB)
    ensure_memory_headroom()

    monkeypatch.setattr(memory_budget, "available_memory_bytes", lambda: None)
    ensure_memory_headroom()


def test_cgroup_headroom_ignores_reclaimable_page_cache(tmp_path):
    (tmp_path / "memory.max").write_text(str(12 * GIB))
    (tmp_path / "memory.current").write_text(str(10 * GIB))
    (tmp_path / "memory.stat").write_text(f"anon {6 * GIB}\ninactive_file {4 * GIB}\n")
    assert _cgroup_headroom(tmp_path) == 6 * GIB


def test_cgroup_headroom_uncapped_is_none(tmp_path):
    (tmp_path / "memory.max").write_text("max")
    (tmp_path / "memory.current").write_text(str(2 * GIB))
    assert _cgroup_headroom(tmp_path) is None


def test_release_freed_memory_is_safe_anywhere():
    release_freed_memory()
