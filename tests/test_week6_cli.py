import json
import subprocess
import sys
from pathlib import Path


def run_script(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *arguments],
        capture_output=True,
        text=True,
        check=False,
    )


def test_load_cli_defaults_to_plan_and_rejects_unconfirmed_10k():
    planned = run_script("scripts/load_test.py")
    assert planned.returncode == 0
    assert json.loads(planned.stdout)["measurements"] is None

    rejected = run_script(
        "scripts/load_test.py", "--mode", "local", "--documents", "10000", "--execute"
    )
    assert rejected.returncode == 2
    assert "confirm-expensive" in rejected.stderr


def test_operations_clis_are_dry_run_and_restore_confirmation_is_stable(tmp_path: Path):
    backup = run_script("scripts/backup.py", "--target", str(tmp_path / "set"))
    consistency = run_script("scripts/check_consistency.py")
    restore = run_script(
        "scripts/restore.py",
        "--source",
        str(tmp_path / "set"),
        "--target-environment",
        "synthetic-stage",
    )
    denied = run_script(
        "scripts/restore.py",
        "--source",
        str(tmp_path / "set"),
        "--target-environment",
        "synthetic-stage",
        "--execute",
        "--confirm",
        "RESTORE:wrong",
    )
    assert backup.returncode == consistency.returncode == restore.returncode == 0
    assert json.loads(backup.stdout)["mode"] == "dry-run"
    assert json.loads(consistency.stdout)["repair_performed"] is False
    assert json.loads(restore.stdout)["mode"] == "dry-run"
    assert denied.returncode == 2
    assert "RESTORE:synthetic-stage" in denied.stderr
