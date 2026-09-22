# Data and ingestion

Uploads are validated by extension, size and duplicate SHA-256, written to MinIO, recorded as `queued`, then processed idempotently by Celery. States are `uploaded`, `queued`, `parsing`, `indexing`, `ready`, `failed_retryable`, `failed_permanent`, `needs_manual_processing`, `quarantined`, and `deleted`.

Locators are page numbers for PDF, paragraphs/tables for DOCX, sheet/row for XLSX, row for CSV, line for text/Markdown, and body/attachment location for EML. EML parsing never fetches remote resources. A PDF without extractable text is sent to manual processing.

Chunks target 700 whitespace tokens with 100-token overlap and never cross source segment boundaries. Every chunk keeps document, space, ordinal and locator. New content with the same filename creates a version; identical content in a space is rejected.

Deletion immediately changes authorization-visible state, then asynchronously removes vectors, chunks and the object. Audit metadata remains without document text.

