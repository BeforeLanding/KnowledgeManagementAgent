# Bounded Agent

## Graph and trust boundary

The compiled LangGraph is `security_check → hybrid_search → authorized_chunk_read → sufficiency_check → answer | refuse → trace`. Security validates server configuration and conversation ownership. The graph exposes only `search_knowledge` and `read_chunks`; both are read-only and a hard counter caps a run at four tool calls. A normal run uses two.

The authenticated user ID, search filters and Provider are injected by server code, not graph/model output. Search derives spaces from PostgreSQL. The read node accepts only chunk IDs returned by that search invocation and repeats PostgreSQL membership, ready-state and deletion checks. No prompt or Provider response is parsed as a tool call, identifier or authorization decision.

## Evidence, conflicts and citations

No authorized context routes directly to a fixed refusal without calling the chat Provider. Authorized contexts are stable-order de-duplicated and bounded by both the read context budget and citation limit. All contexts sent to the Provider are the contexts eligible for citation; citations are generated from those authoritative rows, in the same order, and include their exact document ID, chunk ID, filename, locator and a bounded snippet.

Source excerpts are untrusted data. The OpenAI-compatible prompt forbids following embedded instructions and requires explicit conflict preservation. The deterministic Provider renders each source separately. A conservative pre-check adds an explicit conflict warning when common opposing claims are present, so the response cannot silently conceal detected disagreement.

## Streaming and failure behavior

Graph nodes publish custom events while they execute. Fake mode emits deterministic evidence chunks; OpenAI-compatible mode consumes `stream=true` SSE tokens. Retriable timeout, rate-limit, network and server failures retry only before the first token. After partial output, any failure is terminal and produces `error`, preventing duplicated text. Sync and SSE entry points consume the same execution stream.

The terminal trace node persists only redacted query/answer/citation summaries plus safe node name, tool name, duration, count, status and error code fields. It never stores full context or raw Provider payloads. Failed runs are persisted with the same trace ID, and trace queries are always scoped to the authenticated user.

Week 6 records bounded Agent-node histograms, Provider outcome/latency, refusal and authorized
citation counts. These metrics contain neither trace IDs nor content. A Provider may emit text that
looks like a citation or tool request, but the graph never parses it as either; tool inputs stay in
server closures and citations are generated only from authorized contexts.
