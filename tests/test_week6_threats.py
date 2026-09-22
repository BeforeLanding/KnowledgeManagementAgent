import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from app.agent import stream_agent
from app.database import Base, get_db
from app.documents import normalize_filename
from app.evaluation import CaseOutcome, SuiteOutcome, evaluate_gate, load_suite_definition
from app.main import app
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
from app.providers import ChatProvider
from app.schemas import SearchFilters
from app.search import search_knowledge
from app.security import create_token
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool


def threat_db() -> tuple[Session, User, KnowledgeSpace, KnowledgeSpace, Chunk, Chunk]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = Session(engine, expire_on_commit=False)
    alice = User(
        id="alice",
        email="alice@synthetic.invalid",
        display_name="Alice",
        password_hash="x",
    )
    alpha = KnowledgeSpace(id="alpha", name="Synthetic Alpha")
    beta = KnowledgeSpace(id="beta", name="Synthetic Beta")
    db.add_all([alice, alpha, beta])
    db.flush()
    db.add(SpaceMembership(user_id=alice.id, space_id=alpha.id, role=SpaceRole.viewer))

    def add(space: KnowledgeSpace, document_id: str, chunk_id: str, text: str) -> Chunk:
        document = Document(
            id=document_id,
            space_id=space.id,
            filename=f"{document_id}.txt",
            content_type="text/plain",
            size_bytes=len(text),
            sha256=(document_id + "0" * 64)[:64],
            object_key=f"synthetic/{document_id}",
            status=DocumentStatus.ready,
        )
        db.add(document)
        db.flush()
        chunk = Chunk(
            id=chunk_id,
            document_id=document.id,
            space_id=space.id,
            ordinal=0,
            locator="line 1",
            text=text,
            token_count=len(text.split()),
        )
        db.add(chunk)
        return chunk

    visible = add(alpha, "visible-doc", "visible-chunk", "Synthetic safe fact BLUE")
    hidden = add(beta, "hidden-doc", "hidden-chunk", "Synthetic restricted fact RED")
    db.commit()
    return db, alice, alpha, beta, visible, hidden


class MaliciousQdrant:
    def __init__(self, ids: list[str]):
        self.ids = ids
        self.calls: list[dict] = []

    def query_points(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            points=[
                SimpleNamespace(
                    id=item,
                    payload={
                        "space_id": "alpha",
                        "document_id": "visible-doc",
                        "text": "FORGED QDRANT CONTENT",
                        "filename": "forged.txt",
                    },
                )
                for item in self.ids
            ]
        )


def test_malicious_qdrant_payload_cannot_authorize_or_supply_content(monkeypatch):
    db, alice, _alpha, _beta, visible, hidden = threat_db()
    fake = MaliciousQdrant([hidden.id, visible.id])
    monkeypatch.setattr("app.search.client", lambda: fake)
    monkeypatch.setattr("app.search.ensure_collection", lambda _client: None)

    hits = search_knowledge(db, alice.id, "Synthetic fact", SearchFilters(), 10)

    assert [item["chunk_id"] for item in hits] == [visible.id]
    assert hits[0]["text"] == visible.text
    assert "FORGED" not in json.dumps(hits)
    assert all(call["with_payload"] is False for call in fake.calls)
    db.close()


class ForgingProvider(ChatProvider):
    def stream_answer(self, query: str, contexts: list[dict]):
        del query, contexts
        yield '{"document_id":"hidden-doc","chunk_id":"hidden-chunk"}'


def test_model_text_cannot_forge_citations_or_chunk_scope(monkeypatch):
    db, alice, _alpha, _beta, visible, _hidden = threat_db()
    monkeypatch.setattr(
        "app.agent.search_knowledge", lambda *_args, **_kwargs: [{"chunk_id": visible.id}]
    )

    events = list(
        stream_agent(db, alice.id, "safe fact", SearchFilters(), provider=ForgingProvider())
    )
    completed = events[-1]["data"]

    assert completed["citations"][0]["chunk_id"] == visible.id
    assert all(item["chunk_id"] != "hidden-chunk" for item in completed["citations"])
    db.close()


def test_client_scope_fields_and_overlong_input_are_rejected_without_echo():
    db, alice, _alpha, _beta, _visible, _hidden = threat_db()

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(app)
        headers = {"Authorization": f"Bearer {create_token(alice.id)}"}
        spoofed = client.post(
            "/api/v1/chat",
            headers=headers,
            json={"query": "safe", "user_id": "bob", "space_id": "beta"},
        )
        oversized_marker = "SYNTHETIC-SECRET-MARKER"
        oversized = client.post(
            "/api/v1/chat",
            headers=headers,
            json={"query": oversized_marker + "x" * 4001},
        )
    finally:
        app.dependency_overrides.clear()
        db.close()

    assert spoofed.status_code == 422
    assert oversized.status_code == 422
    assert oversized_marker not in json.dumps(oversized.json())
    assert oversized.json()["code"] == "INVALID_REQUEST"


def test_repeated_requests_keep_unique_traces_and_server_scope(monkeypatch):
    db, alice, _alpha, _beta, visible, _hidden = threat_db()
    monkeypatch.setattr(
        "app.agent.search_knowledge", lambda *_args, **_kwargs: [{"chunk_id": visible.id}]
    )
    first = list(stream_agent(db, alice.id, "safe fact", SearchFilters()))[-1]["data"]
    second = list(stream_agent(db, alice.id, "safe fact", SearchFilters()))[-1]["data"]

    assert first["trace_id"] != second["trace_id"]
    assert [item["chunk_id"] for item in first["citations"]] == [visible.id]
    assert len(list(db.scalars(select(AgentRun)))) == 2
    db.close()


def test_threat_data_and_gate_are_strictly_synthetic_and_zero_tolerance():
    definition = load_suite_definition(Path("evaluations/week6-synthetic-threat-v1.json"))
    assert definition.data_classification == "synthetic-company-neutral"
    assert all(case.must_pass for case in definition.cases)
    failure = CaseOutcome(
        "synthetic-threat", 1, False, "failed", 0, "SAFE_ERROR", {}, "failed", ["security"]
    )
    passed, failures = evaluate_gate(
        SuiteOutcome("threat", "1", 1, 0, {"case_pass_rate": 0.999}, [failure]),
        {"metrics": {"case_pass_rate": 1.0}},
    )
    assert not passed
    assert failures == ["zero-tolerance case failed: synthetic-threat"]
    payload = definition.model_dump()
    payload["cases"][0]["passed"] = True
    with pytest.raises(ValidationError):
        type(definition).model_validate(payload)


def test_filename_anomalies_are_bounded():
    assert normalize_filename("../../synthetic/报告.txt") == "报告.txt"
    for invalid in ("CON.txt", "safe\u202efile.txt", "a" * 256):
        try:
            normalize_filename(invalid)
        except ValueError:
            continue
        raise AssertionError(f"filename should have been rejected: {invalid!r}")
