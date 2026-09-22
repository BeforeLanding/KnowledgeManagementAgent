import logging
import re
import time
import uuid
from collections.abc import Iterator
from typing import Any, TypedDict, cast

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from sqlalchemy.orm import Session

from .config import get_settings
from .models import AgentRun, Conversation
from .observability import CITATIONS, REFUSALS, record_agent_node, record_security_failure
from .providers import ChatProvider, ProviderError, chat_provider
from .schemas import ChatResponse, Citation, SearchFilters
from .search import read_chunks, search_knowledge
from .security import redact, redact_value

REFUSAL = "I could not find sufficient evidence in the accessible knowledge spaces."
logger = logging.getLogger("kma.agent")


class AgentState(TypedDict, total=False):
    query: str
    hits: list[dict]
    contexts: list[dict]
    answer: str
    status: str
    sufficient: bool
    conflict: bool
    tool_calls: int
    citations: list[dict]
    trace: list[dict]


class AgentRunError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        retryable: bool,
        status_code: int = 500,
        trace_id: str | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.status_code = status_code
        self.trace_id = trace_id


def _trace_entry(node: str, started: float, status: str = "completed", **details: Any) -> dict:
    record_agent_node(node, started, "success" if status == "completed" else "failure")
    return redact_value(
        {
            "node": node,
            "duration_ms": max(0, int((time.perf_counter() - started) * 1000)),
            "status": status,
            **details,
        }
    )


def _has_conflict(contexts: list[dict]) -> bool:
    text = " ".join(item["text"].lower() for item in contexts)
    opposing_markers = (
        (" enabled", " disabled"),
        (" allowed", " prohibited"),
        (" is true", " is false"),
        ("可以", "禁止"),
        ("启用", "禁用"),
    )
    marker_conflict = any(
        positive in text and negative in text for positive, negative in opposing_markers
    )
    must_conflict = " must not " in text and re.search(r"\bmust\b(?!\s+not)", text) is not None
    return marker_conflict or must_conflict


def _deduplicate_contexts(contexts: list[dict], limit: int) -> list[dict]:
    result = []
    seen: set[str] = set()
    for item in contexts:
        if item["chunk_id"] in seen:
            continue
        seen.add(item["chunk_id"])
        result.append(item)
        if len(result) >= limit:
            break
    return result


def _citations(contexts: list[dict], limit: int) -> list[Citation]:
    result: list[Citation] = []
    seen: set[str] = set()
    for item in contexts:
        chunk_id = item["chunk_id"]
        if chunk_id in seen:
            continue
        seen.add(chunk_id)
        result.append(
            Citation(
                document_id=item["document_id"],
                chunk_id=chunk_id,
                filename=item["filename"],
                locator=item["locator"],
                snippet=item["text"][:300],
            )
        )
        if len(result) >= limit:
            break
    return result


def _build_graph(
    db: Session,
    user_id: str,
    filters: SearchFilters,
    conversation_id: str | None,
    provider: ChatProvider,
    trace_id: str,
):
    settings = get_settings()

    def security_node(state: AgentState) -> dict:
        started = time.perf_counter()
        if settings.agent_max_tool_calls < 2:
            record_security_failure("configuration")
            raise AgentRunError(
                "AGENT_SECURITY_ERROR", "Agent tool budget is too small", False, 500
            )
        if conversation_id:
            conversation = db.get(Conversation, conversation_id)
            if not conversation or conversation.user_id != user_id:
                record_security_failure("conversation_scope")
                raise AgentRunError(
                    "AGENT_SECURITY_ERROR", "Conversation is not accessible", False, 403
                )
        return {
            "tool_calls": 0,
            "trace": state.get("trace", [])
            + [_trace_entry("security_check", started, scope="server_derived")],
        }

    def search_node(state: AgentState) -> dict:
        started = time.perf_counter()
        writer = get_stream_writer()
        if state["tool_calls"] >= settings.agent_max_tool_calls:
            raise AgentRunError("AGENT_TOOL_LIMIT", "Agent tool-call limit exceeded", False)
        writer({"event": "tool_started", "data": {"tool": "search_knowledge"}})
        hits = search_knowledge(db, user_id, state["query"], filters, top_k=10)
        writer(
            {
                "event": "tool_completed",
                "data": {"tool": "search_knowledge", "result_count": len(hits)},
            }
        )
        return {
            "hits": hits,
            "tool_calls": state["tool_calls"] + 1,
            "trace": state["trace"]
            + [
                _trace_entry(
                    "hybrid_search",
                    started,
                    tool="search_knowledge",
                    result_count=len(hits),
                )
            ],
        }

    def read_node(state: AgentState) -> dict:
        started = time.perf_counter()
        writer = get_stream_writer()
        if state["tool_calls"] >= settings.agent_max_tool_calls:
            raise AgentRunError("AGENT_TOOL_LIMIT", "Agent tool-call limit exceeded", False)
        # IDs are copied only from server-returned hits; neither client nor model can supply them.
        chunk_ids = [item["chunk_id"] for item in state["hits"]]
        writer({"event": "tool_started", "data": {"tool": "read_chunks"}})
        contexts = _deduplicate_contexts(
            read_chunks(db, user_id, chunk_ids, max_words=settings.agent_context_words),
            settings.agent_max_citations,
        )
        writer(
            {
                "event": "tool_completed",
                "data": {"tool": "read_chunks", "result_count": len(contexts)},
            }
        )
        return {
            "contexts": contexts,
            "tool_calls": state["tool_calls"] + 1,
            "trace": state["trace"]
            + [
                _trace_entry(
                    "authorized_chunk_read",
                    started,
                    tool="read_chunks",
                    result_count=len(contexts),
                )
            ],
        }

    def sufficiency_node(state: AgentState) -> dict:
        started = time.perf_counter()
        contexts = state.get("contexts", [])
        sufficient = bool(contexts)
        conflict = _has_conflict(contexts)
        return {
            "sufficient": sufficient,
            "conflict": conflict,
            "trace": state["trace"]
            + [
                _trace_entry(
                    "sufficiency_check",
                    started,
                    evidence_count=len(contexts),
                    sufficient=sufficient,
                    conflict=conflict,
                )
            ],
        }

    def answer_node(state: AgentState) -> dict:
        started = time.perf_counter()
        writer = get_stream_writer()
        pieces: list[str] = []
        if state.get("conflict"):
            warning = "The authorized sources contain conflicting evidence:\n"
            pieces.append(warning)
            writer({"event": "token", "data": {"text": warning}})
        for token in provider.stream_answer(state["query"], state["contexts"]):
            pieces.append(token)
            writer({"event": "token", "data": {"text": token}})
        return {
            "status": "answered",
            "answer": "".join(pieces),
            "trace": state["trace"] + [_trace_entry("answer", started)],
        }

    def refuse_node(state: AgentState) -> dict:
        started = time.perf_counter()
        REFUSALS.labels("insufficient_evidence").inc()
        get_stream_writer()({"event": "token", "data": {"text": REFUSAL}})
        return {
            "status": "insufficient_evidence",
            "answer": REFUSAL,
            "trace": state["trace"] + [_trace_entry("refuse", started)],
        }

    def trace_node(state: AgentState) -> dict:
        started = time.perf_counter()
        citations = _citations(
            state.get("contexts", []) if state["status"] == "answered" else [],
            settings.agent_max_citations,
        )
        writer = get_stream_writer()
        for citation in citations:
            writer({"event": "citation", "data": citation.model_dump()})
        CITATIONS.labels("authorized").inc(len(citations))
        trace = state["trace"] + [
            _trace_entry(
                "trace",
                started,
                tool_calls=state.get("tool_calls", 0),
                citation_count=len(citations),
            )
        ]
        persisted_citations = redact_value([item.model_dump() for item in citations])
        run = AgentRun(
            id=trace_id,
            user_id=user_id,
            conversation_id=conversation_id,
            query=redact(state["query"]),
            status=state["status"],
            answer=redact(state["answer"]),
            citations=persisted_citations,
            trace=redact_value(trace),
            latency_ms=sum(item.get("duration_ms", 0) for item in trace),
        )
        db.add(run)
        db.commit()
        return {"citations": [item.model_dump() for item in citations], "trace": trace}

    graph = StateGraph(AgentState)
    graph.add_node("security_check", security_node)
    graph.add_node("hybrid_search", search_node)
    graph.add_node("authorized_chunk_read", read_node)
    graph.add_node("sufficiency_check", sufficiency_node)
    graph.add_node("answer", answer_node)
    graph.add_node("refuse", refuse_node)
    graph.add_node("trace", trace_node)
    graph.add_edge(START, "security_check")
    graph.add_edge("security_check", "hybrid_search")
    graph.add_edge("hybrid_search", "authorized_chunk_read")
    graph.add_edge("authorized_chunk_read", "sufficiency_check")
    graph.add_conditional_edges(
        "sufficiency_check",
        lambda state: "answer" if state["sufficient"] else "refuse",
        {"answer": "answer", "refuse": "refuse"},
    )
    graph.add_edge("answer", "trace")
    graph.add_edge("refuse", "trace")
    graph.add_edge("trace", END)
    return graph.compile()


def stream_agent(
    db: Session,
    user_id: str,
    query: str,
    filters: SearchFilters,
    conversation_id: str | None = None,
    provider: ChatProvider | None = None,
) -> Iterator[dict]:
    trace_id = str(uuid.uuid4())
    started = time.perf_counter()
    yield {"event": "run_started", "data": {"trace_id": trace_id}}
    latest: AgentState = {"query": query, "trace": []}
    try:
        graph = _build_graph(
            db, user_id, filters, conversation_id, provider or chat_provider(), trace_id
        )
        for mode, item in graph.stream(
            latest, stream_mode=["custom", "updates"]
        ):
            if mode == "custom":
                data = dict(item["data"])
                data["trace_id"] = trace_id
                yield {"event": item["event"], "data": data}
            elif mode == "updates":
                for update in item.values():
                    if isinstance(update, dict):
                        latest.update(cast(AgentState, update))
        response = ChatResponse(
            status=latest["status"],
            answer=latest["answer"],
            citations=[Citation.model_validate(item) for item in latest.get("citations", [])],
            trace_id=trace_id,
        )
        logger.info("agent_run_completed trace_id=%s status=%s", trace_id, response.status)
        yield {
            "event": "run_completed",
            "data": response.model_dump(),
        }
    except Exception as exc:
        db.rollback()
        if isinstance(exc, (ProviderError, AgentRunError)):
            code = exc.code
            retryable = exc.retryable
            status_code = exc.status_code
            message = str(exc)
        else:
            code = "AGENT_INTERNAL_ERROR"
            retryable = True
            status_code = 500
            message = "Agent execution failed"
        safe_message = redact(message)
        logger.warning("agent_run_failed trace_id=%s code=%s", trace_id, code)
        trace = latest.get("trace", []) + [
            _trace_entry("error", started, "failed", code=code, error=safe_message)
        ]
        db.add(
            AgentRun(
                id=trace_id,
                user_id=user_id,
                conversation_id=None,
                query=redact(query),
                status="failed",
                answer="",
                citations=[],
                trace=redact_value(trace),
                latency_ms=int((time.perf_counter() - started) * 1000),
            )
        )
        db.commit()
        yield {
            "event": "error",
            "data": {
                "code": code,
                "message": safe_message,
                "retryable": retryable,
                "trace_id": trace_id,
                "status_code": status_code,
            },
        }


def run_agent(
    db: Session,
    user_id: str,
    query: str,
    filters: SearchFilters,
    conversation_id: str | None = None,
    provider: ChatProvider | None = None,
) -> ChatResponse:
    for item in stream_agent(db, user_id, query, filters, conversation_id, provider):
        if item["event"] == "run_completed":
            return ChatResponse.model_validate(item["data"])
        if item["event"] == "error":
            data = item["data"]
            raise AgentRunError(
                data["code"],
                data["message"],
                data["retryable"],
                data["status_code"],
                data["trace_id"],
            )
    raise AgentRunError("AGENT_INTERNAL_ERROR", "Agent did not complete", True)
