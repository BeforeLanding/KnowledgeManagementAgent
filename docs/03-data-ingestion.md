# Data and ingestion

Uploads are validated by extension, size and duplicate SHA-256, written to MinIO, recorded as `queued`, then processed idempotently by Celery. States are `uploaded`, `queued`, `parsing`, `indexing`, `ready`, `failed_retryable`, `failed_permanent`, `needs_manual_processing`, `quarantined`, and `deleted`.

Locators are page numbers for PDF, paragraphs/tables for DOCX, sheet/row for XLSX, row for CSV, line for text/Markdown, and body/attachment location for EML. EML parsing never fetches remote resources. A PDF without extractable text is sent to manual processing.

Chunks target 700 whitespace tokens with 100-token overlap and never cross source segment boundaries. Every chunk keeps document, space, ordinal and locator. New content with the same filename creates a version; identical content in a space is rejected.

Deletion immediately changes authorization-visible state, then asynchronously removes vectors, chunks and the object. Audit metadata remains without document text.

## State-machine operating rules

Only `failed_retryable`, `failed_permanent`, and `needs_manual_processing` documents can be manually requeued. Active, ready, and deleted documents return a conflict instead of creating concurrent ingestion attempts. A retry first removes any stale vectors and persisted chunks, then assigns fresh chunk IDs; this makes recovery safe after a partial index write.

Parser and no-text failures are terminal until a curator explicitly retries them. Infrastructure and unexpected failures remain `failed_retryable`; the worker retries them up to three times with exponential backoff. Error details are redacted before persistence.

PostgreSQL remains authoritative during asynchronous deletion. Every search result is rechecked against ready, non-deleted documents in an authorized space, so a stale Qdrant point is never returned while physical purge is pending. Object, vector, and chunk deletion operations are idempotent and may be retried independently.
