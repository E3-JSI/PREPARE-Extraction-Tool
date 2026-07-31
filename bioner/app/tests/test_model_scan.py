"""Tests for on-disk model discovery (engine detection + directory scan)."""

import json

from app import model_manager


def _mkmodel(base, name, marker, contents="{}", extra=None):
    """Create a model dir ``name`` under ``base`` with a ``marker`` file."""
    d = base / name
    d.mkdir()
    (d / marker).write_text(contents)
    for f in extra or []:
        (d / f).write_text("{}")
    return d


def test_detect_gliner(tmp_path):
    d = _mkmodel(tmp_path, "g", "gliner_config.json")
    assert model_manager.detect_engine(d) == ("gliner", False)


def test_detect_huggingface(tmp_path):
    d = _mkmodel(tmp_path, "hf", "config.json")
    assert model_manager.detect_engine(d) == ("huggingface", False)


def test_detect_adapter(tmp_path):
    d = _mkmodel(tmp_path, "lora", "adapter_config.json")
    assert model_manager.detect_engine(d) == ("huggingface", True)


def test_adapter_takes_precedence_over_config(tmp_path):
    # An adapter folder that also bundles a transformers config.json is still an adapter.
    d = _mkmodel(tmp_path, "lora2", "adapter_config.json", extra=["config.json"])
    assert model_manager.detect_engine(d) == ("huggingface", True)


def test_gliner_takes_precedence(tmp_path):
    d = _mkmodel(tmp_path, "g2", "gliner_config.json", extra=["config.json"])
    assert model_manager.detect_engine(d) == ("gliner", False)


def test_non_model_dir_returns_none(tmp_path):
    d = tmp_path / "junk"
    d.mkdir()
    (d / "readme.txt").write_text("hi")
    assert model_manager.detect_engine(d) == (None, False)


def test_scan_skips_non_model_dirs_and_files(tmp_path):
    _mkmodel(tmp_path, "gliner-a", "gliner_config.json")
    _mkmodel(tmp_path, ".cache", "notes.txt")  # no engine marker -> skipped
    (tmp_path / "loose-file.bin").write_text("x")  # not a directory -> skipped

    scanned = model_manager.scan_models(str(tmp_path))
    names = {m["dir_name"] for m in scanned}
    assert names == {"gliner-a"}
    entry = scanned[0]
    assert entry["engine"] == "gliner"
    assert entry["is_adapter"] is False
    assert entry["path"].endswith("gliner-a")


def test_scan_reports_adapter_flag(tmp_path):
    _mkmodel(tmp_path, "adapter-x", "adapter_config.json")
    scanned = model_manager.scan_models(str(tmp_path))
    assert scanned[0]["engine"] == "huggingface"
    assert scanned[0]["is_adapter"] is True


def test_scan_version_from_run_folder_name(tmp_path):
    _mkmodel(tmp_path, "run-7-20250101_120000", "gliner_config.json")
    scanned = model_manager.scan_models(str(tmp_path))
    assert scanned[0]["name"] == "run-7-20250101_120000"
    assert scanned[0]["version"] == "20250101_120000"


def test_scan_prefers_metadata_json(tmp_path):
    d = _mkmodel(tmp_path, "run-9-20250101_120000", "gliner_config.json")
    (d / "metadata.json").write_text(json.dumps({"name": "My Model", "version": "2.3"}))
    scanned = model_manager.scan_models(str(tmp_path))
    assert scanned[0]["name"] == "My Model"
    assert scanned[0]["version"] == "2.3"


def test_scan_missing_dir_returns_empty(tmp_path):
    assert model_manager.scan_models(str(tmp_path / "nope")) == []
