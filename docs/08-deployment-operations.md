# Deployment and operations

Copy `.env.example` to `.env`, replace all local credentials, then run `docker compose up --build`. Enable Prometheus with `docker compose --profile observability up --build`. `/health` is liveness and `/metrics` exposes HTTP counters and latency histograms.

Back up PostgreSQL, the MinIO bucket and Qdrant snapshots as one recovery set. Redis is disposable. Restore metadata and objects before the vector snapshot; if the vector snapshot is unavailable, requeue non-deleted documents for indexing.

Rotate JWT, model and storage secrets outside the repository. Terminate TLS at a reverse proxy, restrict MinIO/Qdrant/PostgreSQL to the private network, configure resource limits, and replace demo credentials before any shared deployment.

Operational alerts should cover ingestion failure rate, queue age, search P95, provider error rate, refusal-rate shifts and ACL test failures. A release is rolled back when must-pass evaluation fails or an authorization regression is observed.

## Retrieval operations

Qdrant stores a rebuildable projection. Keep keyword payload indexes for `space_id`, `document_id` and `file_type` plus a datetime index for the ISO-8601 `created_at` payload. PostgreSQL always rechecks membership, requested document IDs, creation dates, filename-derived type, ready state and deletion state before a hit leaves the API. Never bypass this recheck to reduce latency.

After restoring PostgreSQL without a matching Qdrant snapshot, requeue ready, non-deleted documents for indexing and treat search as degraded until reconciliation completes. Stale Qdrant points are safe but reduce recall and consume candidate slots; monitor document/chunk counts in PostgreSQL against Qdrant point counts and rebuild when they drift. Membership revocation and soft deletion take effect immediately through the PostgreSQL checks even if vector cleanup is delayed.

Before release, run the deterministic benchmark with `uv run python scripts/evaluate_retrieval.py` and the complete check list in the roadmap. Investigate any metric drop rather than accepting a regenerated baseline automatically.
