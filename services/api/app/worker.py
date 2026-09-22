from celery import Celery

from .config import get_settings
from .database import SessionLocal
from .ingestion import ingest_once, purge_once
from .models import Document, DocumentStatus
from .parsers import NeedsManualProcessing, PermanentParseError
from .search import delete_document_index, index_chunks
from .security import redact
from .storage import store

settings = get_settings()
celery_app = Celery("kma", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(task_acks_late=True, worker_prefetch_multiplier=1, task_track_started=True)


@celery_app.task(bind=True, max_retries=3)
def ingest_document(self, document_id: str) -> None:
    with SessionLocal() as db:
        document = db.get(Document, document_id)
        if not document or document.status in {DocumentStatus.ready, DocumentStatus.deleted}:
            return
        try:
            ingest_once(
                db,
                document,
                store.get,
                index_chunks,
                delete_document_index,
                chunk_tokens=settings.chunk_tokens,
                chunk_overlap=settings.chunk_overlap,
            )
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
            document.error_message = redact(str(exc))[:1000]
            db.commit()
            raise self.retry(exc=exc, countdown=2 ** self.request.retries) from exc


@celery_app.task(bind=True, max_retries=3)
def purge_document(self, document_id: str) -> None:
    with SessionLocal() as db:
        document = db.get(Document, document_id)
        if not document:
            return
        try:
            purge_once(db, document, store.delete, delete_document_index)
        except Exception as exc:
            raise self.retry(exc=exc, countdown=2 ** self.request.retries) from exc
