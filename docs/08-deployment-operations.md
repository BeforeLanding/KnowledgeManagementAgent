# Deployment and operations

Copy `.env.example` to `.env`, replace all local credentials, then run `docker compose up --build`. Enable Prometheus with `docker compose --profile observability up --build`. `/health` is liveness and `/metrics` exposes HTTP counters and latency histograms.

Back up PostgreSQL, the MinIO bucket and Qdrant snapshots as one recovery set. Redis is disposable. Restore metadata and objects before the vector snapshot; if the vector snapshot is unavailable, requeue non-deleted documents for indexing.

Rotate JWT, model and storage secrets outside the repository. Terminate TLS at a reverse proxy, restrict MinIO/Qdrant/PostgreSQL to the private network, configure resource limits, and replace demo credentials before any shared deployment.

Operational alerts should cover ingestion failure rate, queue age, search P95, provider error rate, refusal-rate shifts and ACL test failures. A release is rolled back when must-pass evaluation fails or an authorization regression is observed.

