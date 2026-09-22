"""Low-cardinality, content-free service metrics.

Metric labels are deliberately mapped to bounded allow-lists. Queries, answers,
filenames, emails, identifiers, errors, and trace IDs must never become labels.
"""

from time import perf_counter

from prometheus_client import Counter, Gauge, Histogram

HTTP_REQUESTS = Counter(
    "kma_http_requests_total", "HTTP requests", ["method", "route", "status"]
)
HTTP_LATENCY = Histogram(
    "kma_http_request_seconds", "HTTP request latency", ["method", "route"]
)
INGESTION_TRANSITIONS = Counter(
    "kma_ingestion_transitions_total", "Document ingestion transitions", ["status"]
)
QUEUE_EVENTS = Counter(
    "kma_queue_events_total", "Bounded queue lifecycle events", ["queue", "event"]
)
QUEUE_ACTIVE = Gauge("kma_queue_active", "Active tasks observed by this process", ["queue"])
QUEUE_ITEM_AGE = Gauge(
    "kma_queue_item_age_seconds", "Age of an item when task processing starts", ["queue"]
)
RETRIEVAL_LATENCY = Histogram(
    "kma_retrieval_stage_seconds", "Retrieval stage latency", ["stage", "result"]
)
AGENT_NODE_LATENCY = Histogram(
    "kma_agent_node_seconds", "Agent node latency", ["node", "result"]
)
PROVIDER_REQUESTS = Counter(
    "kma_provider_requests_total", "Provider request outcomes", ["provider", "result"]
)
PROVIDER_LATENCY = Histogram(
    "kma_provider_request_seconds", "Provider request latency", ["provider", "result"]
)
EVALUATION_GATES = Counter(
    "kma_evaluation_gate_total", "Evaluation gate outcomes", ["suite", "result"]
)
REFUSALS = Counter("kma_agent_refusals_total", "Agent refusals", ["reason"])
CITATIONS = Counter("kma_citations_total", "Citation outcomes", ["result"])
SECURITY_FAILURES = Counter(
    "kma_security_failures_total", "Security boundary failures", ["category"]
)
READINESS = Gauge("kma_dependency_ready", "Dependency readiness", ["dependency"])

_ALLOWED: dict[str, set[str]] = {
    "ingestion_status": {
        "queued",
        "parsing",
        "indexing",
        "ready",
        "failed_retryable",
        "failed_permanent",
        "needs_manual_processing",
        "deleted",
        "other",
    },
    "queue": {"ingestion", "purge", "other"},
    "queue_event": {"dispatched", "dispatch_failed", "started", "completed", "failed", "other"},
    "retrieval_stage": {
        "authorize",
        "dense",
        "sparse",
        "postgres_recheck",
        "rerank",
        "total",
        "other",
    },
    "agent_node": {
        "security_check",
        "hybrid_search",
        "authorized_chunk_read",
        "sufficiency_check",
        "answer",
        "refuse",
        "trace",
        "other",
    },
    "provider": {"fake", "openai", "other"},
    "result": {"success", "failure", "refused", "empty", "other"},
    "suite": {"smoke", "regression", "threat", "other"},
    "security": {
        "authentication",
        "authorization",
        "conversation_scope",
        "citation",
        "prompt_injection",
        "configuration",
        "input",
        "other",
    },
    "dependency": {"postgres", "redis", "qdrant", "minio"},
}


def bounded(kind: str, value: str) -> str:
    """Map an untrusted label to a documented finite set."""
    normalized = value.strip().lower().replace("-", "_")
    return normalized if normalized in _ALLOWED[kind] else "other"


def record_agent_node(node: str, started: float, result: str = "success") -> None:
    AGENT_NODE_LATENCY.labels(
        bounded("agent_node", node), bounded("result", result)
    ).observe(max(0.0, perf_counter() - started))


def record_security_failure(category: str) -> None:
    SECURITY_FAILURES.labels(bounded("security", category)).inc()
