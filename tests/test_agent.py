import asyncio
import json

from app.agent import REFUSAL, stream_agent
from app.database import Base
from app.models import (
    AgentRun,
    Chunk,
    Document,
    DocumentStatus,
    KnowledgeSpace,
    SpaceMembership,
    SpaceRole,
    User,
)
from app.providers import ChatProvider, ProviderError
from app.routes import chat_stream, traces
from app.schemas import ChatRequest, SearchFilters
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool


class RecordingProvider(ChatProvider):
    def __init__(self, pieces: list[str] | None = None, failure: ProviderError | None = None):
        self.pieces = pieces or ["grounded answer"]
        self.failure = failure
        self.contexts: list[dict] = []

    def stream_answer(self, query: str, contexts: list[dict]):
        self.contexts = contexts
        yield from self.pieces
        if self.failure:
            raise self.failure


def make_db() -> tuple[Session, User, User]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = Session(engine)
    first = User(email="first@test.invalid", display_name="First", password_hash="x")
    second = User(email="second@test.invalid", display_name="Second", password_hash="x")
    db.add_all([first, second])
    db.commit()
    return db, first, second


def authorized_context(chunk_id: str = "authorized-chunk", text: str = "The feature is enabled."):
    return {
        "chunk_id": chunk_id,
        "document_id": "authorized-document",
        "filename": "synthetic-policy.txt",
        "locator": "line 7",
        "text": text,
    }


def patch_tools(monkeypatch, contexts: list[dict]):
    searched_id = "server-selected-chunk"

    def fake_search(db, user_id, query, filters, top_k):
        return [{"chunk_id": searched_id}]

    def fake_read(db, user_id, chunk_ids, max_words=6000):
        assert chunk_ids == [searched_id]
        return contexts

    monkeypatch.setattr("app.agent.search_knowledge", fake_search)
    monkeypatch.setattr("app.agent.read_chunks", fake_read)


def test_bounded_graph_event_order_citations_and_safe_trace(monkeypatch):
    db, user, _other = make_db()
    context = authorized_context(text="Contact jane@example.com; token=source-secret.")
    patch_tools(monkeypatch, [context, context])
    provider = RecordingProvider(
        ["Email jane@example.com phone +65 6123 4567 token=answer-secret"]
    )

    events = list(
        stream_agent(db, user.id, "Call +65 6123 4567", SearchFilters(), provider=provider)
    )
    names = [item["event"] for item in events]

    assert names == [
        "run_started",
        "tool_started",
        "tool_completed",
        "tool_started",
        "tool_completed",
        "token",
        "citation",
        "run_completed",
    ]
    assert {item["data"]["trace_id"] for item in events} == {events[0]["data"]["trace_id"]}
    response = events[-1]["data"]
    assert [item["chunk_id"] for item in response["citations"]] == ["authorized-chunk"]
    assert provider.contexts == [context]

    run = db.scalar(select(AgentRun))
    assert run is not None
    assert [item["node"] for item in run.trace] == [
        "security_check",
        "hybrid_search",
        "authorized_chunk_read",
        "sufficiency_check",
        "answer",
        "trace",
    ]
    assert run.trace[-1]["tool_calls"] == 2
    assert "6123" not in run.query
    assert "answer-secret" not in run.answer
    assert "jane@example.com" not in run.answer
    assert "source-secret" not in json.dumps(run.citations)
    assert all("text" not in item for item in run.trace)
    db.close()


def test_no_authorized_evidence_refuses_without_calling_provider(monkeypatch):
    db, user, _other = make_db()
    patch_tools(monkeypatch, [])
    provider = RecordingProvider(failure=AssertionError("provider must not run"))

    events = list(stream_agent(db, user.id, "unknown", SearchFilters(), provider=provider))
    response = events[-1]["data"]

    assert response["status"] == "insufficient_evidence"
    assert response["answer"] == REFUSAL
    assert response["citations"] == []
    assert provider.contexts == []
    db.close()


def test_conflicting_evidence_is_explicit_and_both_sources_are_cited(monkeypatch):
    db, user, _other = make_db()
    contexts = [
        authorized_context("chunk-a", "The feature is enabled."),
        {**authorized_context("chunk-b", "The feature is disabled."), "document_id": "doc-b"},
    ]
    patch_tools(monkeypatch, contexts)

    events = list(
        stream_agent(
            db, user.id, "feature status", SearchFilters(), provider=RecordingProvider()
        )
    )
    response = events[-1]["data"]

    assert response["answer"].startswith("The authorized sources contain conflicting evidence")
    assert [item["chunk_id"] for item in response["citations"]] == ["chunk-a", "chunk-b"]
    db.close()


def test_citations_exclude_inaccessible_deleted_and_non_ready_chunks(monkeypatch):
    db, user, _other = make_db()
    allowed = KnowledgeSpace(name="Allowed citations")
    blocked = KnowledgeSpace(name="Blocked citations")
    db.add_all([allowed, blocked])
    db.flush()
    db.add(SpaceMembership(user_id=user.id, space_id=allowed.id, role=SpaceRole.viewer))

    def add_chunk(space: KnowledgeSpace, status: DocumentStatus, label: str) -> Chunk:
        document = Document(
            space_id=space.id,
            filename=f"{label}.txt",
            content_type="text/plain",
            size_bytes=10,
            sha256=label.ljust(64, "0")[:64],
            object_key=f"synthetic/{label}",
            status=status,
        )
        db.add(document)
        db.flush()
        chunk = Chunk(
            document_id=document.id,
            space_id=space.id,
            ordinal=0,
            locator="line 1",
            text=f"{label} evidence",
            token_count=2,
        )
        db.add(chunk)
        db.flush()
        return chunk

    visible = add_chunk(allowed, DocumentStatus.ready, "visible")
    hidden = add_chunk(blocked, DocumentStatus.ready, "hidden")
    pending = add_chunk(allowed, DocumentStatus.indexing, "pending")
    deleted = add_chunk(allowed, DocumentStatus.deleted, "deleted")
    db.commit()

    ids = [visible.id, hidden.id, pending.id, deleted.id]
    monkeypatch.setattr(
        "app.agent.search_knowledge", lambda *_args, **_kwargs: [{"chunk_id": item} for item in ids]
    )
    events = list(
        stream_agent(db, user.id, "evidence", SearchFilters(), provider=RecordingProvider())
    )
    response = events[-1]["data"]

    assert [item["chunk_id"] for item in response["citations"]] == [visible.id]
    db.close()


def test_provider_midstream_failure_emits_error_and_persists_redacted_failure(monkeypatch):
    db, user, _other = make_db()
    patch_tools(monkeypatch, [authorized_context()])
    provider = RecordingProvider(
        ["partial"],
        ProviderError(
            "PROVIDER_NETWORK_ERROR", "token=provider-secret", retryable=True
        ),
    )

    events = list(stream_agent(db, user.id, "question", SearchFilters(), provider=provider))

    assert [item["event"] for item in events][-2:] == ["token", "error"]
    assert events[-1]["data"]["code"] == "PROVIDER_NETWORK_ERROR"
    assert "provider-secret" not in events[-1]["data"]["message"]
    run = db.scalar(select(AgentRun))
    assert run is not None and run.status == "failed"
    assert "provider-secret" not in json.dumps(run.trace)
    db.close()


def test_traces_are_isolated_to_current_user():
    db, first, second = make_db()
    db.add_all(
        [
            AgentRun(user_id=first.id, query="first", status="answered"),
            AgentRun(user_id=second.id, query="second", status="answered"),
        ]
    )
    db.commit()

    result = traces(first, db)

    assert [item["query"] for item in result] == ["first"]
    db.close()


def test_sse_serializes_incremental_events_with_one_trace_id(monkeypatch):
    db, user, _other = make_db()
    patch_tools(monkeypatch, [authorized_context()])
    monkeypatch.setattr("app.agent.chat_provider", lambda: RecordingProvider(["one", "two"]))
    response = chat_stream(ChatRequest(query="question"), user, db)

    async def consume() -> str:
        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)
        return "".join(chunks)

    body = asyncio.run(consume())
    blocks = [block for block in body.split("\n\n") if block]
    events = []
    for block in blocks:
        event_line, data_line = block.split("\n", 1)
        events.append((event_line.removeprefix("event: "), json.loads(data_line[6:])))

    assert [name for name, _data in events] == [
        "run_started",
        "tool_started",
        "tool_completed",
        "tool_started",
        "tool_completed",
        "token",
        "token",
        "citation",
        "run_completed",
    ]
    assert len({data["trace_id"] for _name, data in events}) == 1
    db.close()


def test_sse_covers_refusal_and_provider_failure(monkeypatch):
    def render(contexts: list[dict], provider: ChatProvider) -> list[tuple[str, dict]]:
        db, user, _other = make_db()
        patch_tools(monkeypatch, contexts)
        monkeypatch.setattr("app.agent.chat_provider", lambda: provider)
        response = chat_stream(ChatRequest(query="question"), user, db)

        async def consume() -> str:
            chunks = []
            async for chunk in response.body_iterator:
                chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)
            return "".join(chunks)

        blocks = [block for block in asyncio.run(consume()).split("\n\n") if block]
        db.close()
        return [
            (block.split("\n", 1)[0][7:], json.loads(block.split("\n", 1)[1][6:]))
            for block in blocks
        ]

    refusal = render([], RecordingProvider())
    assert [name for name, _data in refusal][-2:] == ["token", "run_completed"]
    assert refusal[-1][1]["status"] == "insufficient_evidence"

    failure = render(
        [authorized_context()],
        RecordingProvider(
            failure=ProviderError("PROVIDER_TIMEOUT", "timed out", retryable=True)
        ),
    )
    assert failure[-1][0] == "error"
    assert failure[-1][1]["code"] == "PROVIDER_TIMEOUT"
    assert "run_completed" not in [name for name, _data in failure]
