"""Create a quiesced PostgreSQL/MinIO/Qdrant recovery set; dry-run by default."""

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "api"))

from app.config import get_settings  # noqa: E402
from app.maintenance import backup_plan, safe_child  # noqa: E402
from app.search import COLLECTION  # noqa: E402
from app.search import client as qdrant_client  # noqa: E402
from app.storage import store  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--quiesced", action="store_true")
    parser.add_argument("--confirm")
    return parser.parse_args(argv)


def execute_backup(target: Path) -> dict:
    target.mkdir(parents=True, exist_ok=False)
    postgres_path = target / "postgres.dump"
    with postgres_path.open("wb") as output:
        completed = subprocess.run(
            ["docker", "compose", "exec", "-T", "postgres", "pg_dump", "-U", "kma", "-Fc", "kma"],
            cwd=ROOT,
            stdout=output,
            stderr=subprocess.PIPE,
            check=False,
        )
    if completed.returncode:
        raise RuntimeError("PostgreSQL backup failed; see the local command output")
    object_root = target / "minio"
    object_count = 0
    for item in store.client.list_objects(store.bucket, recursive=True):
        destination = safe_child(object_root, item.object_name)
        destination.parent.mkdir(parents=True, exist_ok=True)
        store.client.fget_object(store.bucket, item.object_name, str(destination))
        object_count += 1
    qdrant = qdrant_client()
    snapshot = qdrant.create_snapshot(COLLECTION)
    settings = get_settings()
    if snapshot is None or not snapshot.name:
        raise RuntimeError("Qdrant did not return a snapshot name")
    snapshot_path = safe_child(target, snapshot.name)
    with httpx.stream(
        "GET",
        f"{settings.qdrant_url.rstrip('/')}/collections/{COLLECTION}/snapshots/{snapshot.name}",
        timeout=60,
    ) as response:
        response.raise_for_status()
        with snapshot_path.open("wb") as output:
            for chunk in response.iter_bytes():
                output.write(chunk)
    manifest = {
        "schema_version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "components": {
            "postgres": postgres_path.name,
            "minio": {"directory": "minio", "objects": object_count},
            "qdrant": {"collection": COLLECTION, "snapshot": snapshot_path.name},
        },
        "redis": "disposable-not-backed-up",
        "release": settings.release_version,
    }
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        if not args.execute:
            print(json.dumps(backup_plan(args.target), indent=2))
            return 0
        if not args.quiesced or args.confirm != "BACKUP":
            raise ValueError("execution requires --quiesced --confirm BACKUP")
        print(json.dumps(execute_backup(args.target), indent=2))
        return 0
    except (ValueError, OSError, RuntimeError, httpx.HTTPError) as exc:
        message = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        print(json.dumps({"status": "failed", "error": message}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
