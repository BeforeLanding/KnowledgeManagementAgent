import time
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy.orm import Session

from .models import AgentRun
from .providers import chat_provider
from .schemas import ChatResponse, Citation, SearchFilters
from .search import read_chunks, search_knowledge
from .security import redact


class AgentState(TypedDict, total=False):
    query: str
    hits: list[dict]
    contexts: list[dict]
    answer: str
    status: str
    trace: list[dict]


def run_agent(
    db: Session,
    user_id: str,
    query: str,
    filters: SearchFilters,
    conversation_id: str | None = None,
) -> ChatResponse:
    started = time.perf_counter()

    def search_node(state: AgentState) -> dict:
        hits = search_knowledge(db, user_id, state["query"], filters, top_k=10)
        return {
            "hits": hits,
            "trace": state.get("trace", [])
            + [{"tool": "search_knowledge", "result_count": len(hits)}],
        }

    def read_node(state: AgentState) -> dict:
        contexts = read_chunks(db, user_id, [item["chunk_id"] for item in state["hits"]])
        return {
            "contexts": contexts,
            "trace": state["trace"] + [{"tool": "read_chunks", "result_count": len(contexts)}],
        }

    def answer_node(state: AgentState) -> dict:
        contexts = state.get("contexts", [])
        if not contexts:
            return {
                "status": "insufficient_evidence",
                "answer": (
                    "I could not find sufficient evidence in the accessible knowledge spaces."
                ),
            }
        return {"status": "answered", "answer": chat_provider().answer(state["query"], contexts)}

    graph = StateGraph(AgentState)
    graph.add_node("search", search_node)
    graph.add_node("read", read_node)
    graph.add_node("answer", answer_node)
    graph.add_edge(START, "search")
    graph.add_edge("search", "read")
    graph.add_edge("read", "answer")
    graph.add_edge("answer", END)
    result = graph.compile().invoke({"query": query, "trace": []})

    citations = [
        Citation(
            document_id=item["document_id"],
            chunk_id=item["chunk_id"],
            filename=item["filename"],
            locator=item["locator"],
            snippet=item["text"][:300],
        )
        for item in result.get("contexts", [])[:6]
    ]
    run = AgentRun(
        user_id=user_id,
        conversation_id=conversation_id,
        query=redact(query),
        status=result["status"],
        answer=redact(result["answer"]),
        citations=[item.model_dump() for item in citations],
        trace=result.get("trace", []),
        latency_ms=int((time.perf_counter() - started) * 1000),
    )
    db.add(run)
    db.commit()
    return ChatResponse(
        status=result["status"], answer=result["answer"], citations=citations, trace_id=run.id
    )
