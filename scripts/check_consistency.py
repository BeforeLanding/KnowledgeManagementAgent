"""Report PostgreSQL/MinIO/Qdrant drift without deleting or repairing data."""

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "api"))

from app.database import SessionLocal  # noqa: E402
from app.maintenance import ChunkRecord, DocumentRecord, reconcile  # noqa: E402
from app.models import Chunk, Document  # noqa: E402
from app.search import COLLECTION  # noqa: E402
from app.search import client as qdrant_client  # noqa: E402
from app.storage import store  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--limit", type=int, default=100_000)
    parser.add_argument("--output", type=Path)
    return parser.parse_args(argv)


def collect(limit: int) -> dict:
    if not 1 <= limit <= 1_000_000:
        raise ValueError("limit must be between 1 and 1000000")
    with SessionLocal() as db:
        documents = [
            DocumentRecord(item.id, item.object_key, item.status.value, item.deleted_at is not None)
            for item in db.scalars(select(Document).limit(limit))
        ]
        chunks = [
            ChunkRecord(item.id, item.document_id)
            for item in db.scalars(select(Chunk).limit(limit))
        ]
    vector_ids: set[str] = set()
    offset = None
    while len(vector_ids) < limit:
        points, offset = qdrant_client().scroll(
            COLLECTION,
            limit=min(1_000, limit - len(vector_ids)),
            offset=offset,
            with_payload=False,
            with_vectors=False,
        )
        vector_ids.update(str(item.id) for item in points)
        if offset is None:
            break
    object_keys = {
        item.object_name for item in store.client.list_objects(store.bucket, recursive=True)
    }
    return reconcile(documents, chunks, vector_ids, object_keys)


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        if args.execute:
            report = collect(args.limit)
        else:
            report = {
                "operation": "consistency-check",
                "mode": "dry-run",
                "authority": "postgres",
                "checks": [
                    "missing_vectors",
                    "stale_vectors",
                    "orphan_chunks",
                    "missing_objects",
                    "lifecycle_mismatches",
                ],
                "repair_performed": False,
            }
        rendered = json.dumps(report, indent=2, sort_keys=True)
        print(rendered)
        if args.output:
            args.output.write_text(rendered + "\n", encoding="utf-8")
        return 0 if not args.execute or report["consistent"] else 1
    except (ValueError, OSError, RuntimeError) as exc:
        message = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        print(json.dumps({"status": "failed", "error": message}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
