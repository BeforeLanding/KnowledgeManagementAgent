from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from app.database import Base
from app.models import (
    Chunk,
    Document,
    DocumentStatus,
    KnowledgeSpace,
    SpaceMembership,
    SpaceRole,
    User,
)
from app.schemas import SearchFilters
from app.search import (
    RankedCandidate,
    ensure_collection,
    lexical_rerank_score,
    read_chunks,
    reciprocal_rank_fusion,
    rerank_candidates,
    search_knowledge,
)
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session


def add_document(
    db: Session,
    space_id: str,
    name: str,
    text: str,
    *,
    status: DocumentStatus = DocumentStatus.ready,
    created_at: datetime | None = None,
) -> tuple[Document, Chunk]:
    document = Document(
        space_id=space_id,
        filename=name,
        content_type="text/plain",
        size_bytes=len(text),
        sha256=(name.encode().hex() + "0" * 64)[:64],
        object_key=f"synthetic/{name}",
        status=status,
        created_at=created_at or datetime(2026, 1, 10, tzinfo=UTC),
    )
    db.add(document)
    db.flush()
    chunk = Chunk(
        document_id=document.id,
        space_id=space_id,
        ordinal=0,
        locator="line 1",
        text=text,
        token_count=len(text.split()),
    )
    db.add(chunk)
    db.flush()
    return document, chunk


class FakeQdrant:
    def __init__(self, dense_ids: list[str], sparse_ids: list[str], hook=None):
        self.dense_ids = dense_ids
        self.sparse_ids = sparse_ids
        self.calls: list[dict] = []
        self.hook = hook

    def query_points(self, **kwargs):
        self.calls.append(kwargs)
        if self.hook:
            self.hook(len(self.calls))
        ids = self.dense_ids if kwargs["using"] == "dense" else self.sparse_ids
        return SimpleNamespace(points=[SimpleNamespace(id=item) for item in ids])


def test_existing_collection_adds_missing_payload_indexes():
    created: list[tuple[str, object]] = []
    fake = SimpleNamespace(
        collection_exists=lambda _name: True,
        get_collection=lambda _name: SimpleNamespace(
            payload_schema={"space_id": object(), "document_id": object()}
        ),
        create_payload_index=lambda _collection, field, schema: created.append((field, schema)),
    )

    ensure_collection(fake)

    assert [field for field, _schema in created] == ["file_type", "created_at"]


def test_rrf_rewards_candidates_present_in_both_rankings():
    fused = reciprocal_rank_fusion([["dense-only", "both"], ["both", "sparse-only"]])

    assert [item.chunk_id for item in fused] == ["both", "dense-only", "sparse-only"]
    assert fused[0].retrieval_score == pytest.approx(1 / 62 + 1 / 61)


def test_lightweight_rerank_is_bounded_and_stable():
    assert lexical_rerank_score("alpha beta", "alpha beta alpha") == pytest.approx(0.9)
    candidates = [RankedCandidate("b", 1.0), RankedCandidate("a", 1.0)]

    ranked = rerank_candidates("alpha beta", candidates, {"a": "alpha beta", "b": "noise"})

    assert [item.chunk_id for item, _score in ranked] == ["a", "b"]
    assert all(0 <= score <= 1 for _item, score in ranked)


def test_search_uses_hybrid_queries_and_postgres_authoritative_filters(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(email="viewer@test.invalid", display_name="Viewer", password_hash="x")
        allowed = KnowledgeSpace(name="Synthetic Allowed")
        blocked = KnowledgeSpace(name="Synthetic Blocked")
        db.add_all([user, allowed, blocked])
        db.flush()
        db.add(SpaceMembership(user_id=user.id, space_id=allowed.id, role=SpaceRole.viewer))
        target, target_chunk = add_document(db, allowed.id, "target.TXT", "alpha beta")
        old, old_chunk = add_document(
            db,
            allowed.id,
            "old.txt",
            "alpha beta old",
            created_at=datetime(2025, 1, 1, tzinfo=UTC),
        )
        wrong_type, wrong_type_chunk = add_document(
            db, allowed.id, "wrong.pdf", "alpha beta pdf"
        )
        deleted, deleted_chunk = add_document(
            db, allowed.id, "deleted.txt", "alpha beta deleted", status=DocumentStatus.deleted
        )
        blocked_document, blocked_chunk = add_document(
            db, blocked.id, "blocked.txt", "alpha beta confidential"
        )
        db.commit()
        all_ids = [
            target_chunk.id,
            old_chunk.id,
            wrong_type_chunk.id,
            deleted_chunk.id,
            blocked_chunk.id,
        ]
        fake = FakeQdrant(all_ids, list(reversed(all_ids)))
        monkeypatch.setattr("app.search.client", lambda: fake)
        monkeypatch.setattr("app.search.ensure_collection", lambda _client: None)
        filters = SearchFilters(
            document_ids=[target.id, old.id, wrong_type.id, deleted.id, blocked_document.id],
            file_types=[".TXT"],
            created_from=datetime(2026, 1, 1, tzinfo=UTC),
            created_to=datetime(2026, 1, 31, tzinfo=UTC),
        )

        hits = search_knowledge(db, user.id, "alpha beta", filters, 10)

        assert [item["document_id"] for item in hits] == [target.id]
        assert hits[0]["text"] == target_chunk.text
        assert [call["using"] for call in fake.calls] == ["dense", "sparse"]
        assert all(call["with_payload"] is False for call in fake.calls)
        payload_filter = fake.calls[0]["query_filter"].model_dump(mode="json")
        assert allowed.id in str(payload_filter)
        assert blocked.id not in str(payload_filter)
        assert "txt" in str(payload_filter)


def test_membership_is_rechecked_after_vector_retrieval(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(email="revoked@test.invalid", display_name="Revoked", password_hash="x")
        space = KnowledgeSpace(name="Synthetic Revocation")
        db.add_all([user, space])
        db.flush()
        db.add(SpaceMembership(user_id=user.id, space_id=space.id, role=SpaceRole.viewer))
        _document, chunk = add_document(db, space.id, "revoked.txt", "alpha")
        db.commit()

        def revoke(call_number: int) -> None:
            if call_number == 2:
                persisted = db.scalar(
                    select(SpaceMembership).where(SpaceMembership.user_id == user.id)
                )
                db.delete(persisted)
                db.commit()

        fake = FakeQdrant([chunk.id], [chunk.id], revoke)
        monkeypatch.setattr("app.search.client", lambda: fake)
        monkeypatch.setattr("app.search.ensure_collection", lambda _client: None)

        assert search_knowledge(db, user.id, "alpha", SearchFilters(), 10) == []


def test_read_chunks_rechecks_acl_visibility_and_preserves_requested_order():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(email="reader@test.invalid", display_name="Reader", password_hash="x")
        allowed = KnowledgeSpace(name="Synthetic Read Allowed")
        blocked = KnowledgeSpace(name="Synthetic Read Blocked")
        db.add_all([user, allowed, blocked])
        db.flush()
        db.add(SpaceMembership(user_id=user.id, space_id=allowed.id, role=SpaceRole.viewer))
        _first, first = add_document(db, allowed.id, "first.txt", "first")
        _second, second = add_document(db, allowed.id, "second.txt", "second")
        _blocked, blocked_chunk = add_document(db, blocked.id, "blocked.txt", "secret")
        db.commit()

        rows = read_chunks(db, user.id, [second.id, blocked_chunk.id, first.id])

        assert [item["chunk_id"] for item in rows] == [second.id, first.id]
        assert all(item["text"] != "secret" for item in rows)
