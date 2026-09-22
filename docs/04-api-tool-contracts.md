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

Chat returns `status`, `answer`, `citations[]`, and `trace_id`. SSE event names are `run_started`, `tool_started`, `tool_completed`, `token`, `citation`, `run_completed`, and `error`. Every event contains the same `trace_id`; each `data:` line is one JSON object. Tool events contain only the stable tool name and safe result count. `run_completed` uses the same fields as synchronous Chat. `error` contains `code`, redacted `message`, `retryable`, and `trace_id`, and is terminal.

Event order is `run_started`, zero or more paired tool events, zero or more tokens, citations, then `run_completed`; a failure replaces completion with `error`. Refusals produce a refusal token and complete with no citations. The service sets no-buffering headers and does not execute the full Agent before opening the event generator.
