import hashlib
from datetime import UTC, datetime

import pytest
from app.database import Base
from app.documents import duplicate_document, next_document_version, normalize_filename
from app.models import Document, DocumentStatus, KnowledgeSpace
from app.routes import enqueue_ingestion
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


def test_filename_is_reduced_to_safe_basename():
    assert normalize_filename(r"C:\synthetic\journal.md") == "journal.md"
    assert normalize_filename("../../brief.txt") == "brief.txt"
    with pytest.raises(ValueError):
        normalize_filename("..")
    with pytest.raises(ValueError):
        normalize_filename("bad\x00name.txt")


def test_duplicate_and_version_rules_include_history_but_ignore_deleted_duplicate():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        space = KnowledgeSpace(name="Synthetic Space")
        db.add(space)
        db.flush()
        digest = hashlib.sha256(b"synthetic").hexdigest()
        first = Document(
            space_id=space.id,
            filename="journal.md",
            content_type="text/markdown",
            size_bytes=9,
            sha256=digest,
            object_key="synthetic/journal.md",
            version=1,
            status=DocumentStatus.ready,
        )
        db.add(first)
        db.commit()

        assert duplicate_document(db, space.id, digest).id == first.id
        assert next_document_version(db, space.id, "journal.md") == 2

        first.status = DocumentStatus.deleted
        first.deleted_at = datetime.now(UTC)
        db.commit()
        assert duplicate_document(db, space.id, digest) is None
        assert next_document_version(db, space.id, "journal.md") == 2


def test_queue_failure_leaves_document_retryable(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        space = KnowledgeSpace(name="Synthetic Queue")
        db.add(space)
        db.flush()
        document = Document(
            space_id=space.id,
            filename="journal.md",
            content_type="text/markdown",
            size_bytes=9,
            sha256="a" * 64,
            object_key="synthetic/journal.md",
            status=DocumentStatus.queued,
        )
        db.add(document)
        db.commit()

        def fail_dispatch(_document_id: str) -> None:
            raise ConnectionError("redis token=synthetic-secret")

        monkeypatch.setattr("app.routes.ingest_document.delay", fail_dispatch)
        with pytest.raises(ConnectionError):
            enqueue_ingestion(db, document)

        assert document.status == DocumentStatus.failed_retryable
        assert document.error_code == "QUEUE_ERROR"
        assert "synthetic-secret" not in document.error_message
