"""Tests for on-disk model deletion (``model_manager.remove_model_dir``)."""

import pytest

from app import model_manager


def _mkmodel(base, name, marker="gliner_config.json"):
    d = base / name
    d.mkdir()
    (d / marker).write_text("{}")
    return d


def test_removes_model_dir(tmp_path):
    d = _mkmodel(tmp_path, "run-1-20260101_000000")
    model_manager.remove_model_dir(str(tmp_path), "run-1-20260101_000000")
    assert not d.exists()


def test_rejects_path_traversal_names(tmp_path):
    _mkmodel(tmp_path, "victim")
    for name in ("../victim", "a/victim", "..", ".", ""):
        with pytest.raises(ValueError):
            model_manager.remove_model_dir(str(tmp_path), name)
    assert (tmp_path / "victim").exists()


def test_rejects_non_model_dir(tmp_path):
    d = tmp_path / "junk"
    d.mkdir()
    (d / "readme.txt").write_text("hi")
    with pytest.raises(ValueError):
        model_manager.remove_model_dir(str(tmp_path), "junk")
    assert d.exists()


def test_missing_dir_raises_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        model_manager.remove_model_dir(str(tmp_path), "nope")
