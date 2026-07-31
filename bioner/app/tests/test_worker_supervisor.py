import os
from pathlib import Path

from app.worker_supervisor import _zombie_child_pids


def _write_stat(proc_root: Path, pid: int, comm: str, state: str, ppid: int):
    d = proc_root / str(pid)
    d.mkdir()
    (d / "stat").write_text(f"{pid} ({comm}) {state} {ppid} 0 0 0 -1 4194560")


def test_detects_zombie_child(tmp_path):
    _write_stat(tmp_path, 105, "python", "Z", os.getpid())
    assert _zombie_child_pids(tmp_path) == {105}


def test_ignores_live_children_and_other_parents(tmp_path):
    _write_stat(tmp_path, 45, "python", "S", os.getpid())  # alive
    _write_stat(tmp_path, 200, "python", "Z", 99999)  # someone else's zombie
    assert _zombie_child_pids(tmp_path) == set()


def test_handles_comm_with_spaces_and_parens(tmp_path):
    _write_stat(tmp_path, 300, "weird (name) here", "Z", os.getpid())
    assert _zombie_child_pids(tmp_path) == {300}


def test_missing_proc_root_is_noop(tmp_path):
    assert _zombie_child_pids(tmp_path / "does-not-exist") == set()
