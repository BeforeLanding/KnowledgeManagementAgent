# Week 6 verification and release screenshot

## Automated locally

The default unit suite uses SQLite, fake Qdrant responses, Fake Provider and explicitly labelled
company-neutral synthetic fixtures. It verifies threat boundaries, low-cardinality metrics,
readiness behavior, production configuration rejection, CLI dry-runs and confirmations, the local
microbenchmark, Web types and existing Week 1–5 behavior. Run:

```bash
uv run pytest
uv run ruff check .
uv run mypy services/api/app
pnpm test:web
pnpm build:web
docker compose config --quiet
uv run python scripts/evaluate.py --suite smoke
uv run python scripts/evaluate.py --suite regression
uv run python scripts/evaluate.py --suite threat
```

## Requires Compose or a separately authorized environment

Fresh PostgreSQL/MinIO/Qdrant/Redis readiness, actual ingestion, queue behavior, backups, destructive
restore drills, reconciliation against service state, and the Compose/10k load tier require an
explicit environment. Expensive tests are never part of `pytest`. Production-like testing also
requires HTTPS, written authorization, runtime credentials and an agreed maintenance window.

## Reproducible screenshot instructions

1. Copy `.env.example` to `.env`, keep `APP_ENV=development`, and use only the bundled synthetic
   demo identities and `scripts/load_demo.py` content.
2. Start `docker compose up --build`, wait for `/health/ready` to return `ready`, then load the demo.
3. Open `http://localhost:3000`, sign in with the documented demo administrator, and select
   **Evaluation & traces**.
4. Run the smoke suite once. Capture the page with the three Week 6 cards (Readiness, Latest gate,
   Security · 24h) and the synthetic suite summary. Do not expand traces or citations.
5. Before publishing, inspect the image: it must contain no real names, employer data, private
   hostnames, credentials, raw errors, source text, email, high-cardinality IDs or sensitive trace.

No screenshot binary is committed because the UI state depends on a live Compose run. These steps
are the reproducible release artifact and constrain it to company-neutral synthetic data.

## Current limits

Week 6 does not provide Kubernetes, production SSO, SIEM, a large dashboard, external secret-store
automation, full malware scanning, OCR, a calibrated LLM judge, a penetration-test certificate,
measured 10k capacity, SLA or automatic data repair.
