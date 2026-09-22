# Deployment and operations

Copy `.env.example` to `.env`, replace all local credentials, then run `docker compose up --build`. Enable Prometheus with `docker compose --profile observability up --build`. `/health` is liveness and `/metrics` exposes HTTP counters and latency histograms.

The API container runs `alembic upgrade head` before idempotent demo seeding and startup. Apply the
same migration step before starting a separately deployed API; Week 5 is migration
`0002_week5_evaluations`.

Back up PostgreSQL, the MinIO bucket and Qdrant snapshots as one recovery set. Redis is disposable. Restore metadata and objects before the vector snapshot; if the vector snapshot is unavailable, requeue non-deleted documents for indexing.

Rotate JWT, model and storage secrets outside the repository. Terminate TLS at a reverse proxy, restrict MinIO/Qdrant/PostgreSQL to the private network, configure resource limits, and replace demo credentials before any shared deployment.

Operational alerts should cover ingestion failure rate, queue age, search P95, provider error rate, refusal-rate shifts and ACL test failures. A release is rolled back when must-pass evaluation fails or an authorization regression is observed.

## Agent and Provider operations

Fake mode is the deterministic default and makes no model network call. For an OpenAI-compatible endpoint set `MODEL_PROVIDER=openai`, `OPENAI_BASE_URL`, `OPENAI_API_KEY` and `CHAT_MODEL`. Connect, read, write and pool timeouts are independently configurable with `PROVIDER_*_TIMEOUT_SECONDS`; `PROVIDER_MAX_ATTEMPTS` is capped at five and defaults to three. Retry backoff applies only before any token is emitted. Never log request bodies, authorization headers or Provider response bodies.

SSE proxies must disable response buffering and allow connections longer than the configured Provider read timeout. Monitor terminal `error` events by stable error code, graph latency, refusal rate and tool result counts. A completed trace must show no more than four tool calls; the normal graph shows exactly two. The Fake Provider intentionally emits deterministic evidence-sized token chunks rather than character-level model tokens, which preserves incremental event semantics for local and unit testing.

## Retrieval operations

Qdrant stores a rebuildable projection. Keep keyword payload indexes for `space_id`, `document_id` and `file_type` plus a datetime index for the ISO-8601 `created_at` payload. PostgreSQL always rechecks membership, requested document IDs, creation dates, filename-derived type, ready state and deletion state before a hit leaves the API. Never bypass this recheck to reduce latency.

After restoring PostgreSQL without a matching Qdrant snapshot, requeue ready, non-deleted documents for indexing and treat search as degraded until reconciliation completes. Stale Qdrant points are safe but reduce recall and consume candidate slots; monitor document/chunk counts in PostgreSQL against Qdrant point counts and rebuild when they drift. Membership revocation and soft deletion take effect immediately through the PostgreSQL checks even if vector cleanup is delayed.

Before release, run `uv run python scripts/evaluate.py --suite smoke` and
`uv run python scripts/evaluate.py --suite regression`, followed by the complete check list in
the roadmap. Both commands are external-service-free and return CI-friendly exit codes. A metric
drop above two percentage points, or any ACL, prompt-injection or must-pass failure, blocks release.
Investigate a regression rather than regenerating a baseline. Baseline updates require an explicit
write/overwrite flag and a reviewed diff. The API limits synchronous runs (25 cases by default);
do not raise that limit to turn the request worker into a batch evaluation service.
