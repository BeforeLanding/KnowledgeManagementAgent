"""Pure planning and reconciliation helpers for safe operations scripts."""

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath


@dataclass(frozen=True)
class DocumentRecord:
    id: str
    object_key: str
    status: str
    deleted: bool


@dataclass(frozen=True)
class ChunkRecord:
    id: str
    document_id: str


def backup_plan(target: Path) -> dict:
    return {
        "operation": "backup",
        "mode": "dry-run",
        "target": str(target.resolve()),
        "components": ["postgres", "minio", "qdrant"],
        "redis": "disposable-not-backed-up",
        "requires_quiesced_writes": True,
        "data_classification": "metadata-and-private-runtime-data",
    }


def restore_plan(source: Path, target_environment: str | None) -> dict:
    return {
        "operation": "restore",
        "mode": "dry-run",
        "source": str(source.resolve()),
        "target_environment": target_environment,
        "order": ["postgres", "minio", "qdrant"],
        "destructive": True,
        "redis": "discard-and-recreate",
    }


def validate_restore_confirmation(target_environment: str | None, confirmation: str | None) -> None:
    if not target_environment or target_environment.strip().lower() in {"", "unknown"}:
        raise ValueError("--target-environment must name an explicit target")
    expected = f"RESTORE:{target_environment}"
    if confirmation != expected:
        raise ValueError(f"restore requires --confirm {expected}")


def safe_child(root: Path, relative_name: str) -> Path:
    """Resolve a backup member without permitting absolute paths or traversal."""
    normalized_name = relative_name.replace("\\", "/")
    posix_name = PurePosixPath(normalized_name)
    windows_name = PureWindowsPath(relative_name)
    if (
        posix_name.is_absolute()
        or windows_name.is_absolute()
        or bool(windows_name.drive)
        or ".." in posix_name.parts
    ):
        raise ValueError("backup member path is unsafe")
    relative = Path(*posix_name.parts)
    root_resolved = root.resolve()
    destination = (root_resolved / relative).resolve()
    if destination != root_resolved and root_resolved not in destination.parents:
        raise ValueError("backup member path escapes the target")
    return destination


def reconcile(
    documents: Iterable[DocumentRecord],
    chunks: Iterable[ChunkRecord],
    vector_ids: set[str],
    object_keys: set[str],
) -> dict:
    """Report drift only. PostgreSQL rows determine expected visibility and lifecycle."""
    document_map = {item.id: item for item in documents}
    chunk_list = list(chunks)
    chunk_ids = {item.id for item in chunk_list}
    visible_chunks = {
        item.id
        for item in chunk_list
        if (document := document_map.get(item.document_id))
        and document.status == "ready"
        and not document.deleted
    }
    active_objects = {
        item.object_key
        for item in document_map.values()
        if not item.deleted and item.status != "deleted"
    }
    orphan_chunks = sorted(
        item.id for item in chunk_list if item.document_id not in document_map
    )
    lifecycle_mismatches = sorted(
        item.id
        for item in chunk_list
        if (document := document_map.get(item.document_id))
        and (document.deleted or document.status == "deleted")
    )
    report = {
        "authority": "postgres",
        "counts": {
            "documents": len(document_map),
            "chunks": len(chunk_ids),
            "vectors": len(vector_ids),
            "objects": len(object_keys),
        },
        "missing_vectors": sorted(visible_chunks - vector_ids),
        "stale_vectors": sorted(vector_ids - visible_chunks),
        "orphan_chunks": orphan_chunks,
        "missing_objects": sorted(active_objects - object_keys),
        "lifecycle_mismatches": lifecycle_mismatches,
        "repair_performed": False,
    }
    report["consistent"] = not any(
        report[name]
        for name in (
            "missing_vectors",
            "stale_vectors",
            "orphan_chunks",
            "missing_objects",
            "lifecycle_mismatches",
        )
    )
    return report
