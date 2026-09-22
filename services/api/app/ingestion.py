from collections.abc import Callable

from sqlalchemy import delete
from sqlalchemy.orm import Session

from .models import Chunk, Document, DocumentStatus
from .parsers import chunk_segments, parse_bytes

GetObject = Callable[[str], bytes]
DeleteObject = Callable[[str], None]
IndexChunks = Callable[[Document, list[Chunk]], None]
DeleteIndex = Callable[[str], None]


def ingest_once(
    db: Session,
    document: Document,
    get_object: GetObject,
    index_chunks: IndexChunks,
    delete_index: DeleteIndex,
    *,
    chunk_tokens: int,
    chunk_overlap: int,
) -> None:
    """Run one idempotent ingestion attempt for a persisted document."""
    document.status = DocumentStatus.parsing
    db.commit()

    segments = parse_bytes(document.filename, get_object(document.object_key))
    parsed = chunk_segments(segments, chunk_tokens, chunk_overlap)
    if not parsed:
        from .parsers import PermanentParseError

        raise PermanentParseError("Document did not contain indexable text")

    # A previous attempt may have committed chunks or partially written vectors.
    # Clear both derived stores before assigning fresh chunk identifiers.
    delete_index(document.id)
    db.execute(delete(Chunk).where(Chunk.document_id == document.id))
    chunks = [
        Chunk(
            document_id=document.id,
            space_id=document.space_id,
            ordinal=index,
            locator=segment.locator,
            text=segment.text,
            token_count=len(segment.text.split()),
        )
        for index, segment in enumerate(parsed)
    ]
    db.add_all(chunks)
    document.status = DocumentStatus.indexing
    db.commit()

    index_chunks(document, chunks)
    document.status = DocumentStatus.ready
    document.error_code = None
    document.error_message = None
    db.commit()


def purge_once(
    db: Session,
    document: Document,
    delete_object: DeleteObject,
    delete_index: DeleteIndex,
) -> None:
    """Idempotently remove document-derived content while retaining audit metadata."""
    delete_index(document.id)
    delete_object(document.object_key)
    db.execute(delete(Chunk).where(Chunk.document_id == document.id))
    db.commit()
