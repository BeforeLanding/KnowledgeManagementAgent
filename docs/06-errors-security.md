# Errors and security

User-fixable failures return stable 4xx responses. Network, rate-limit and provider 5xx failures retry with exponential backoff up to three times. Permanent parse errors stop; empty scanned PDFs require manual processing. A document is never `ready` until both metadata and index writes succeed.

Authorization is enforced before retrieval and again while reading chunks. Model-proposed space IDs or chunk IDs are untrusted. Documents are prompt-injection content, not instructions. The answer prompt explicitly requires source-only answers and preserves conflicts.

Trace fields redact common email, phone and secret patterns before persistence. Application logs never include original document text. Files with unsupported active formats are rejected, macros are never executed, EML remote resources are not fetched, and secrets live only in runtime configuration.

Known MVP limitations: access tokens are held in browser session storage rather than production-grade HttpOnly cookies; MIME signature inspection and archive-bomb scanning need a dedicated upload gateway before internet exposure; refresh-token rotation is modelled but not yet exposed as an endpoint.

