from celery import Celery
from sqlalchemy import delete

from .config import get_settings
from .database import SessionLocal
from .models import Chunk, Document, DocumentStatus
from .parsers import NeedsManualProcessing, PermanentParseError, chunk_segments, parse_bytes
from .search import delete_document_index, index_chunks
from .storage import store

settings = get_settings()
celery_app = Celery("kma", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(task_acks_late=True, worker_prefetch_multiplier=1, task_track_started=True)


@celery_app.task(bind=True, autoretry_for=(ConnectionError,), retry_backoff=True, max_retries=3)
def ingest_document(self, document_id: str) -> None:
    with SessionLocal() as db:
        document = db.get(Document, document_id)
        if not document or document.status in {DocumentStatus.ready, DocumentStatus.deleted}:
            return
        try:
            document.status = DocumentStatus.parsing
            db.commit()
            segments = parse_bytes(document.filename, store.get(document.object_key))
            parsed = chunk_segments(segments, settings.chunk_tokens, settings.chunk_overlap)
            if not parsed:
                raise PermanentParseError("Document did not contain indexable text")
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
        except NeedsManualProcessing as exc:
            document.status = DocumentStatus.needs_manual_processing
            document.error_code = "NO_TEXT_LAYER"
            document.error_message = str(exc)
            db.commit()
        except PermanentParseError as exc:
            document.status = DocumentStatus.failed_permanent
            document.error_code = "PARSE_ERROR"
            document.error_message = str(exc)
            db.commit()
        except Exception as exc:
            document.status = DocumentStatus.failed_retryable
            document.error_code = "INGESTION_ERROR"
            document.error_message = str(exc)[:1000]
            db.commit()
            raise


@celery_app.task(bind=True, autoretry_for=(ConnectionError,), retry_backoff=True, max_retries=3)
def purge_document(self, document_id: str) -> None:
    with SessionLocal() as db:
        document = db.get(Document, document_id)
        if not document:
            return
        delete_document_index(document.id)
        store.delete(document.object_key)
        db.execute(delete(Chunk).where(Chunk.document_id == document.id))
        db.commit()
