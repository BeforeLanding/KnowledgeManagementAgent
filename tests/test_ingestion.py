from app.database import Base
from app.ingestion import ingest_once, purge_once
from app.models import Chunk, Document, DocumentStatus, KnowledgeSpace
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session


def make_document(db: Session) -> Document:
    space = KnowledgeSpace(name="Synthetic Ingestion")
    db.add(space)
    db.flush()
    document = Document(
        space_id=space.id,
        filename="journal.txt",
        content_type="text/plain",
        size_bytes=18,
        sha256="a" * 64,
        object_key="synthetic/journal.txt",
        status=DocumentStatus.queued,
    )
    db.add(document)
    db.commit()
    return document


def test_ingestion_is_idempotent_across_retries():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    deleted_indexes: list[str] = []
    indexed_batches: list[list[str]] = []
    with Session(engine) as db:
        document = make_document(db)

        def run() -> None:
            ingest_once(
                db,
                document,
                lambda _key: b"alpha beta gamma delta",
                lambda _document, chunks: indexed_batches.append([chunk.id for chunk in chunks]),
                deleted_indexes.append,
                chunk_tokens=3,
                chunk_overlap=1,
            )

        run()
        assert document.status == DocumentStatus.ready
        assert db.scalar(select(func.count()).select_from(Chunk)) == 2

        document.status = DocumentStatus.failed_retryable
        db.commit()
        run()

        assert document.status == DocumentStatus.ready
        assert db.scalar(select(func.count()).select_from(Chunk)) == 2
        assert deleted_indexes == [document.id, document.id]
        assert set(indexed_batches[0]).isdisjoint(indexed_batches[1])


def test_purge_removes_derived_content_and_is_repeatable():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    deleted_objects: list[str] = []
    deleted_indexes: list[str] = []
    with Session(engine) as db:
        document = make_document(db)
        db.add(
            Chunk(
                document_id=document.id,
                space_id=document.space_id,
                ordinal=0,
                locator="line 1",
                text="synthetic",
                token_count=1,
            )
        )
        document.status = DocumentStatus.deleted
        db.commit()

        for _ in range(2):
            purge_once(db, document, deleted_objects.append, deleted_indexes.append)

        assert db.scalar(select(func.count()).select_from(Chunk)) == 0
        assert deleted_objects == [document.object_key, document.object_key]
        assert deleted_indexes == [document.id, document.id]
