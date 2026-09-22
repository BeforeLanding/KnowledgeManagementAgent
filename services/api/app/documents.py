import re
import unicodedata
from pathlib import PurePosixPath

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Document, DocumentStatus

RETRYABLE_DOCUMENT_STATUSES = {
    DocumentStatus.failed_retryable,
    DocumentStatus.failed_permanent,
    DocumentStatus.needs_manual_processing,
}


def normalize_filename(value: str) -> str:
    """Return a storage-safe basename while preserving the user-visible name."""
    normalized = unicodedata.normalize("NFKC", value)
    filename = PurePosixPath(normalized.replace("\\", "/")).name.strip()
    if not filename or filename in {".", ".."}:
        raise ValueError("A valid filename is required")
    if len(filename) > 255:
        raise ValueError("Filename exceeds 255 characters")
    if re.search(r"[\x00-\x1f\x7f\u202a-\u202e\u2066-\u2069]", filename):
        raise ValueError("Filename contains control characters")
    stem = filename.rsplit(".", 1)[0].rstrip(" .").upper()
    reserved = {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }
    if stem in reserved:
        raise ValueError("Filename uses a reserved device name")
    return filename


def duplicate_document(
    db: Session, space_id: str, sha256: str
) -> Document | None:
    return db.scalar(
        select(Document).where(
            Document.space_id == space_id,
            Document.sha256 == sha256,
            Document.deleted_at.is_(None),
        )
    )


def next_document_version(db: Session, space_id: str, filename: str) -> int:
    current = db.scalar(
        select(func.max(Document.version)).where(
            Document.space_id == space_id,
            Document.filename == filename,
        )
    )
    return (current or 0) + 1
