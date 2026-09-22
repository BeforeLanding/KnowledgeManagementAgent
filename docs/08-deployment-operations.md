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
do not raise that limit to turn the request worker into a batch evaluation service. Run the Week 6
threat Gate as well: `uv run python scripts/evaluate.py --suite threat`.

## Health, metrics and alerts

`/health/live` proves only that the API process can serve requests. `/health/ready` checks
PostgreSQL, Redis, Qdrant and MinIO, returns 503 when any are unavailable, and exposes only a
bounded code and latency. `/health` remains the compatible liveness alias. The authenticated
`/api/v1/operations/status` supplies the Web release view with dependency status, the latest Gate
and aggregate 24-hour failed/refusal counts.

Prometheus metrics include `kma_ingestion_transitions_total`, `kma_queue_events_total`,
`kma_queue_active`, `kma_queue_item_age_seconds`, `kma_retrieval_stage_seconds`,
`kma_agent_node_seconds`, `kma_provider_requests_total`, `kma_provider_request_seconds`,
`kma_evaluation_gate_total`, `kma_agent_refusals_total`, `kma_citations_total`,
`kma_security_failures_total` and `kma_dependency_ready`. Labels are finite allow-lists. Never add
query, answer, source text, filename, email, credential, raw error, trace ID, user/document/chunk ID
or arbitrary suite name labels. `infra/alerts.yml` provides lightweight readiness, retrieval P95,
Provider, ingestion and zero-tolerance security alerts; tune rates only from measured traffic.
Safe UUID request/Agent trace IDs are returned in headers/responses and included in content-free
completion/failure log lines. They deliberately do not become metric labels; correlate aggregate
metrics by time window and use the UUID only to join an individual redacted trace to safe logs.

## Backup, restore and reconciliation

Quiesce uploads and workers before creating a recovery set. Preview with
`uv run python scripts/backup.py --target PATH`; execution additionally requires
`--execute --quiesced --confirm BACKUP`. The set contains a PostgreSQL dump, private MinIO object
copies, a Qdrant snapshot and a manifest. Redis is intentionally excluded and recreated empty.
The development Compose file binds MinIO/Qdrant maintenance ports to loopback only; when running
scripts on the host, override `MINIO_ENDPOINT=127.0.0.1:9000` and
`QDRANT_URL=http://127.0.0.1:6333`. Remove even those loopback bindings in production and run the
same scripts from an authorized maintenance host on the private network.

Restore into an explicitly named, isolated target and validate the manifest first. Preview with
`uv run python scripts/restore.py --source PATH --target-environment NAME`. Execution requires
`--execute --confirm RESTORE:NAME`. Restore PostgreSQL, then MinIO, then Qdrant; run Alembic and the
consistency check before opening traffic. The restore uses destructive database replacement, so a
fresh pre-restore backup and operator review are mandatory.

`uv run python scripts/check_consistency.py` is dry-run. Add `--execute` for a read-only comparison
of PostgreSQL document/chunk rows, Qdrant point IDs and MinIO keys. It reports missing/stale vectors,
orphan chunks, missing objects and lifecycle mismatches with exit 1 on drift. It never repairs or
deletes data. Investigate from PostgreSQL state; rebuild derived vectors or objects only through a
separately reviewed procedure.

## Load test tiers and performance boundaries

`scripts/generate_synthetic_load.py` creates repeatable company-neutral manifests. The load CLI
defaults to plan mode and enforces at most 10,000 documents, concurrency 32, 100,000 requests and
one hour. At 5,000 or more documents it also requires `--confirm-expensive`.

- Local mode measures actual in-process generation, bounded queue behavior, lookup/Agent-like
  latency, throughput, injected retry recovery, tracemalloc peak and serialized index size. It does
  not measure the deployed stack.
- Compose mode, when explicitly executed with credentials supplied only through the named secret
  environment variable, uploads synthetic documents, polls lifecycle state, and mixes search/chat
  requests. Resource and Qdrant-size fields remain null unless an external collector measures them.
- Production-like mode is optional, explicit, HTTPS-only and read-only. Never target an environment
  without written authorization and a maintenance window.

Every result is JSON plus a stderr summary and stable exit code: 0 pass/plan, 1 measured threshold
failure, 2 invalid input/runtime failure. No committed 10k, Compose or production-like result exists
for Week 6; therefore this repository makes no production capacity or SLA claim.

## Release, rollback and recovery

Compose runs Alembic as a one-shot dependency before API or worker startup; application code no
longer calls `create_all`. Validate a fresh `upgrade head`, then run all Python/Web checks and the
smoke, regression and threat Gates. In production, set `APP_ENV=production`, disable demo seeding,
provide non-default JWT/MinIO secrets, and configure an HTTPS OpenAI-compatible endpoint and model.
The app rejects unsafe production settings.

Terminate TLS at a reviewed reverse proxy. Expose only the proxy/Web edge; keep PostgreSQL, Redis,
Qdrant and MinIO on the private backend network. Store secrets outside Compose files, cap CPU/memory,
retain the configured log rotation, and protect Prometheus from public access. These are deployment
requirements/advice; TLS, external secret stores and host monitoring are not provisioned here.

For rollback, stop traffic and workers, preserve a recovery set, deploy the previous image, run only
the migrations compatible with that image, restore the matched recovery set if schema/data rollback
is required, run reconciliation and all zero-tolerance Gates, then reopen traffic. Never downgrade
or delete production data automatically.
