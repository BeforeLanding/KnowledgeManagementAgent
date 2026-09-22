"""Restore an explicit recovery set; always dry-run unless precisely confirmed."""

import argparse
import json
import subprocess
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "api"))

from app.config import get_settings  # noqa: E402
from app.maintenance import restore_plan, safe_child, validate_restore_confirmation  # noqa: E402
from app.search import COLLECTION  # noqa: E402
from app.storage import store  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--target-environment")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm")
    return parser.parse_args(argv)


def execute_restore(source: Path) -> dict:
    manifest_path = source / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1:
        raise ValueError("unsupported recovery manifest schema")
    postgres_path = safe_child(source, manifest["components"]["postgres"])
    object_root = safe_child(source, manifest["components"]["minio"]["directory"])
    snapshot_name = manifest["components"]["qdrant"]["snapshot"]
    snapshot_path = safe_child(source, snapshot_name)
    collection = manifest["components"]["qdrant"]["collection"]
    if collection != COLLECTION:
        raise ValueError("recovery set targets an unexpected Qdrant collection")
    if not postgres_path.is_file() or not object_root.is_dir() or not snapshot_path.is_file():
        raise ValueError("recovery set is incomplete")
    with postgres_path.open("rb") as backup:
        completed = subprocess.run(
            [
                "docker",
                "compose",
                "exec",
                "-T",
                "postgres",
                "pg_restore",
                "-U",
                "kma",
                "--clean",
                "--if-exists",
                "-d",
                "kma",
            ],
            cwd=ROOT,
            stdin=backup,
            stderr=subprocess.PIPE,
            check=False,
        )
    if completed.returncode:
        raise RuntimeError("PostgreSQL restore failed; remaining components were not restored")
    for path in object_root.rglob("*"):
        if path.is_file():
            store.client.fput_object(
                store.bucket, path.relative_to(object_root).as_posix(), str(path)
            )
    settings = get_settings()
    with snapshot_path.open("rb") as snapshot_file:
        response = httpx.post(
            f"{settings.qdrant_url.rstrip('/')}/collections/{collection}/snapshots/upload",
            files={"snapshot": (snapshot_path.name, snapshot_file)},
            params={"priority": "snapshot"},
            timeout=120,
        )
    response.raise_for_status()
    return {"status": "restored", "audit": {"components": ["postgres", "minio", "qdrant"]}}


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        if not args.execute:
            print(json.dumps(restore_plan(args.source, args.target_environment), indent=2))
            return 0
        validate_restore_confirmation(args.target_environment, args.confirm)
        if not (args.source / "manifest.json").is_file():
            raise ValueError("source must contain manifest.json")
        print(json.dumps(execute_restore(args.source), indent=2))
        return 0
    except (
        KeyError,
        TypeError,
        ValueError,
        OSError,
        RuntimeError,
        json.JSONDecodeError,
        httpx.HTTPError,
    ) as exc:
        message = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        print(json.dumps({"status": "failed", "error": message}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
