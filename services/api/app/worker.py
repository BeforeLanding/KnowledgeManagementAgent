from datetime import UTC, datetime

from celery import Celery

from .config import get_settings
from .database import SessionLocal
from .ingestion import ingest_once, purge_once
from .models import Document, DocumentStatus
from .observability import INGESTION_TRANSITIONS, QUEUE_ACTIVE, QUEUE_EVENTS, QUEUE_ITEM_AGE
from .parsers import NeedsManualProcessing, PermanentParseError
from .search import delete_document_index, index_chunks
from .security import redact
from .storage import store

settings = get_settings()
celery_app = Celery("kma", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(task_acks_late=True, worker_prefetch_multiplier=1, task_track_started=True)


@celery_app.task(bind=True, max_retries=3)
def ingest_document(self, document_id: str) -> None:
    QUEUE_EVENTS.labels("ingestion", "started").inc()
    QUEUE_ACTIVE.labels("ingestion").inc()
    with SessionLocal() as db:
        document = db.get(Document, document_id)
        if not document or document.status in {DocumentStatus.ready, DocumentStatus.deleted}:
            QUEUE_ACTIVE.labels("ingestion").dec()
            return
        created_at = document.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        QUEUE_ITEM_AGE.labels("ingestion").set(
            max(0.0, (datetime.now(UTC) - created_at).total_seconds())
        )
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
            INGESTION_TRANSITIONS.labels("ready").inc()
            QUEUE_EVENTS.labels("ingestion", "completed").inc()
        except NeedsManualProcessing as exc:
            document.status = DocumentStatus.needs_manual_processing
            document.error_code = "NO_TEXT_LAYER"
            document.error_message = str(exc)
            db.commit()
            INGESTION_TRANSITIONS.labels("needs_manual_processing").inc()
            QUEUE_EVENTS.labels("ingestion", "failed").inc()
        except PermanentParseError as exc:
            document.status = DocumentStatus.failed_permanent
            document.error_code = "PARSE_ERROR"
            document.error_message = str(exc)
            db.commit()
            INGESTION_TRANSITIONS.labels("failed_permanent").inc()
            QUEUE_EVENTS.labels("ingestion", "failed").inc()
        except Exception as exc:
            document.status = DocumentStatus.failed_retryable
            document.error_code = "INGESTION_ERROR"
            document.error_message = redact(str(exc))[:1000]
            db.commit()
            INGESTION_TRANSITIONS.labels("failed_retryable").inc()
            QUEUE_EVENTS.labels("ingestion", "failed").inc()
            raise self.retry(exc=exc, countdown=2 ** self.request.retries) from exc
        finally:
            QUEUE_ACTIVE.labels("ingestion").dec()


@celery_app.task(bind=True, max_retries=3)
def purge_document(self, document_id: str) -> None:
    QUEUE_EVENTS.labels("purge", "started").inc()
    QUEUE_ACTIVE.labels("purge").inc()
    with SessionLocal() as db:
        document = db.get(Document, document_id)
        if not document:
            QUEUE_ACTIVE.labels("purge").dec()
            return
        try:
            purge_once(db, document, store.delete, delete_document_index)
            QUEUE_EVENTS.labels("purge", "completed").inc()
        except Exception as exc:
            QUEUE_EVENTS.labels("purge", "failed").inc()
            raise self.retry(exc=exc, countdown=2 ** self.request.retries) from exc
        finally:
            QUEUE_ACTIVE.labels("purge").dec()
