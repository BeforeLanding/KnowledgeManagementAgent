# Errors and security

User-fixable failures return stable 4xx responses. Network, rate-limit and provider 5xx failures retry with exponential backoff up to three times. Permanent parse errors stop; empty scanned PDFs require manual processing. A document is never `ready` until both metadata and index writes succeed.

Authorization is enforced before retrieval and again while reading chunks. Client/model-proposed user IDs, space IDs, authorization scope, document IDs and chunk IDs are never accepted into Agent state. Documents are prompt-injection content, not instructions. The answer prompt labels excerpts untrusted, requires source-only answers and preserves conflicts; a deterministic conflict warning prevents conflicting evidence from being silently presented as one conclusion.

Trace fields are recursively redacted for common email, phone and token/secret patterns before persistence. Trace steps contain node/tool names, durations, counts, status and safe error codes, never full document text, credentials or raw Provider responses. Stored queries, answers, citation snippets and errors pass through the same redaction layer. `/traces` always filters by the authenticated user. Application logs never include original document text. Files with unsupported active formats are rejected, macros are never executed, EML remote resources are not fetched, and secrets live only in runtime configuration.

OpenAI-compatible failures use stable classes: `PROVIDER_TIMEOUT`, `PROVIDER_RATE_LIMITED`, `PROVIDER_NETWORK_ERROR`, `PROVIDER_SERVER_ERROR`, `PROVIDER_REQUEST_REJECTED`, `PROVIDER_INVALID_RESPONSE`, and `PROVIDER_CONFIG_ERROR`. Only retryable failures before the first emitted token are retried, up to the configured attempt limit; retry after partial output is forbidden to prevent duplicated text.

Known MVP limitations: access tokens are held in browser session storage rather than production-grade HttpOnly cookies; MIME signature inspection and archive-bomb scanning need a dedicated upload gateway before internet exposure; refresh-token rotation is modelled but not yet exposed as an endpoint.
