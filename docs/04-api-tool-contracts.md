# API and tool contracts

All `/api/v1` endpoints except login require a bearer access token. Errors use `{code,message,retryable,trace_id}`.

| Method | Path | Purpose |
|---|---|---|
| POST | `/auth/login` | Issue access and refresh tokens |
| GET | `/auth/me` | Current user |
| GET | `/spaces` | Authorized spaces and roles |
| GET/POST | `/documents` | List or upload documents |
| POST | `/documents/{id}/retry` | Retry failed ingestion |
| DELETE | `/documents/{id}` | Soft-delete and purge |
| POST | `/search` | Authorized hybrid retrieval |
| POST | `/chat` | Synchronous grounded answer |
| POST | `/chat/stream` | SSE answer events |
| GET | `/traces` | Current user's redacted runs |
| POST | `/evaluations/smoke` | Deterministic regression run |

`search_knowledge` accepts query, document/date/type filters and top-k ≤20. `space_ids` never appear in the public contract: the server derives them. `read_chunks` accepts chunk IDs and a context budget, rechecks space and ready-document status, and returns source locators. `list_sources` is represented by document metadata endpoints and must follow the same membership check when expanded.

Chat returns `status`, `answer`, `citations[]`, and `trace_id`. SSE event names are `run_started`, `tool_started`, `tool_completed`, `token`, `citation`, `run_completed`, and `error`.

