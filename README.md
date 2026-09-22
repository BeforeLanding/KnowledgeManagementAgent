# Knowledge Management Agent

An evaluation-driven, bilingual enterprise RAG agent with knowledge-space ACLs, hybrid retrieval, grounded citations, trace replay, and deterministic regression checks. The repository contains only synthetic, company-neutral data.

## Quick start

```bash
copy .env.example .env
docker compose up --build
python scripts/load_demo.py
```

Open `http://localhost:3000` and sign in with `admin@example.com` / `Admin123!`. The other seeded accounts are `curator@example.com` / `Curator123!` and `viewer@example.com` / `Viewer123!`.

For an OpenAI-compatible model, set `MODEL_PROVIDER=openai`, `OPENAI_BASE_URL`, `OPENAI_API_KEY`, and `CHAT_MODEL`. Fake mode is deterministic and requires no paid API.

## Local development

```bash
uv sync --dev
uv run --directory services/api python -m app.seed
uv run uvicorn app.main:app --reload --app-dir services/api
pnpm install
pnpm dev:web
```

Run checks with `uv run pytest`, `uv run ruff check .`, `uv run mypy services/api/app`, and `pnpm build:web`.

## Architecture

The Next.js web app calls a FastAPI service. PostgreSQL owns identity, ACL, metadata, traces and evaluations; MinIO stores originals; Celery/Redis processes ingestion; Qdrant performs dense+sparse RRF retrieval. The Agent is a bounded LangGraph with only read-only tools. See [architecture](docs/02-architecture.md) and [API contracts](docs/04-api-tool-contracts.md).

## Safety boundary

Do not commit employer data, internal prompts, credentials, emails, logs, or derived evaluation cases without written approval. See [open-source boundary](docs/09-open-source-boundary.md).
