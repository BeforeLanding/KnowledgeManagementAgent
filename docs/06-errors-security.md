# Errors and security

User-fixable failures return stable 4xx responses. Network, rate-limit and provider 5xx failures retry with exponential backoff up to three times. Permanent parse errors stop; empty scanned PDFs require manual processing. A document is never `ready` until both metadata and index writes succeed.

Authorization is enforced before retrieval and again while reading chunks. Client/model-proposed user IDs, space IDs, authorization scope, document IDs and chunk IDs are never accepted into Agent state. Documents are prompt-injection content, not instructions. The answer prompt labels excerpts untrusted, requires source-only answers and preserves conflicts; a deterministic conflict warning prevents conflicting evidence from being silently presented as one conclusion.

Trace fields are recursively redacted for common email, phone and token/secret patterns before persistence. Trace steps contain node/tool names, durations, counts, status and safe error codes, never full document text, credentials or raw Provider responses. Stored queries, answers, citation snippets and errors pass through the same redaction layer. `/traces` always filters by the authenticated user. Application logs never include original document text. Files with unsupported active formats are rejected, macros are never executed, EML remote resources are not fetched, and secrets live only in runtime configuration.

OpenAI-compatible failures use stable classes: `PROVIDER_TIMEOUT`, `PROVIDER_RATE_LIMITED`, `PROVIDER_NETWORK_ERROR`, `PROVIDER_SERVER_ERROR`, `PROVIDER_REQUEST_REJECTED`, `PROVIDER_INVALID_RESPONSE`, and `PROVIDER_CONFIG_ERROR`. Only retryable failures before the first emitted token are retried, up to the configured attempt limit; retry after partial output is forbidden to prevent duplicated text.

Known MVP limitations: access tokens are held in browser session storage rather than production-grade HttpOnly cookies; MIME signature inspection and archive-bomb scanning need a dedicated upload gateway before internet exposure; refresh-token rotation is modelled but not yet exposed as an endpoint.

Evaluation files are accepted only when explicitly labelled `synthetic-company-neutral`.
Acting users are resolved from trusted server data, not request bodies. The Runner recomputes all
outcomes and validates every citation against PostgreSQL; suite expectations, Qdrant payloads,
model output and clients cannot declare authorization or a pass. Persisted evaluation rows contain
configuration, aggregate numbers, stable error categories and redacted summaries only. They do not
contain document bodies, credentials, raw sensitive traces, raw Provider responses or invisible
citations. Viewer and curator run listings are requester-scoped; cross-user execution and
inspection require an administrator role.

## Week 6 threat model and release controls

Protected decisions are authenticated user identity, current memberships, knowledge-space scope,
document readiness/deletion, chunk visibility, citation validity and evaluation Gate status.
Untrusted parties include clients, model output, source documents, Qdrant payloads, evaluation
files, load scripts and the Web UI. None can set those protected decisions. Unknown request fields
are rejected; searches request no Qdrant payload and PostgreSQL supplies every returned field.

Direct and indirect instructions inside documents remain data. Citation-looking model text is only
answer text; citations are constructed from authorized rows after the model stream. Security
metrics use bounded categories only. Queries, answers, filenames, user email, IDs, credentials,
raw errors, raw Provider responses and source text are forbidden as labels or readiness details.

Production startup rejects default/short JWT secrets, local MinIO credentials, demo seeding,
non-HTTPS OpenAI-compatible endpoints, missing model credentials and Fake Provider mode. This is
application hardening, not a claim of penetration testing, certification, complete upload malware
scanning or production SSO.
