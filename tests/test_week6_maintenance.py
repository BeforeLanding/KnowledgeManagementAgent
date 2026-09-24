from pathlib import Path

import pytest
from app.maintenance import (
    ChunkRecord,
    DocumentRecord,
    backup_plan,
    reconcile,
    restore_plan,
    safe_child,
    validate_restore_confirmation,
)


def test_backup_and_restore_plans_are_non_destructive_by_default(tmp_path: Path):
    backup = backup_plan(tmp_path / "backup")
    restore = restore_plan(tmp_path / "backup", "staging-synthetic")
    assert backup["mode"] == "dry-run"
    assert backup["redis"] == "disposable-not-backed-up"
    assert restore["mode"] == "dry-run"
    assert restore["destructive"] is True


def test_restore_requires_exact_named_target_confirmation():
    with pytest.raises(ValueError):
        validate_restore_confirmation(None, None)
    with pytest.raises(ValueError):
        validate_restore_confirmation("production", "RESTORE:staging")
    validate_restore_confirmation("staging-synthetic", "RESTORE:staging-synthetic")


def test_backup_member_paths_cannot_escape_target(tmp_path: Path):
    assert safe_child(tmp_path, "objects/synthetic.txt").parent == (tmp_path / "objects").resolve()
    unsafe_names = [
        "../outside.txt",
        "..\\outside.txt",
        "/outside.txt",
        "C:/outside.txt",
        "C:outside.txt",
        "\\\\server\\share\\outside.txt",
    ]
    for unsafe_name in unsafe_names:
        with pytest.raises(ValueError):
            safe_child(tmp_path, unsafe_name)


def test_consistency_report_finds_all_drift_without_repairing():
    documents = [
        DocumentRecord("ready", "objects/ready", "ready", False),
        DocumentRecord("deleted", "objects/deleted", "deleted", True),
    ]
    chunks = [
        ChunkRecord("missing-vector", "ready"),
        ChunkRecord("deleted-chunk", "deleted"),
        ChunkRecord("orphan", "missing-document"),
    ]
    report = reconcile(
        documents,
        chunks,
        {"stale-vector", "deleted-chunk"},
        {"objects/unexpected"},
    )
    assert report["consistent"] is False
    assert report["missing_vectors"] == ["missing-vector"]
    assert report["stale_vectors"] == ["deleted-chunk", "stale-vector"]
    assert report["orphan_chunks"] == ["orphan"]
    assert report["missing_objects"] == ["objects/ready"]
    assert report["lifecycle_mismatches"] == ["deleted-chunk"]
    assert report["repair_performed"] is False
