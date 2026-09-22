from collections import Counter
from dataclasses import dataclass
from time import perf_counter

from qdrant_client import QdrantClient, models
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from .config import get_settings
from .models import Chunk, Document, DocumentStatus, SpaceMembership
from .observability import RETRIEVAL_LATENCY
from .providers import embedding_provider, terms
from .schemas import SearchFilters

COLLECTION = "knowledge_chunks"
RRF_RANK_CONSTANT = 60
RETRIEVAL_CANDIDATE_FLOOR = 20
RETRIEVAL_CANDIDATE_MULTIPLIER = 4


@dataclass(frozen=True)
class RankedCandidate:
    chunk_id: str
    retrieval_score: float


def reciprocal_rank_fusion(
    rankings: list[list[str]], rank_constant: int = RRF_RANK_CONSTANT
) -> list[RankedCandidate]:
    """Fuse ranked lists deterministically with reciprocal rank fusion."""
    if rank_constant < 1:
        raise ValueError("rank_constant must be positive")
    scores: dict[str, float] = {}
    first_seen: dict[str, int] = {}
    seen_order = 0
    for ranking in rankings:
        for rank, chunk_id in enumerate(dict.fromkeys(ranking), start=1):
            if chunk_id not in first_seen:
                first_seen[chunk_id] = seen_order
                seen_order += 1
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (rank_constant + rank)
    ordered = sorted(scores, key=lambda item: (-scores[item], first_seen[item], item))
    return [RankedCandidate(chunk_id=item, retrieval_score=scores[item]) for item in ordered]


def lexical_rerank_score(query: str, text: str) -> float:
    """Return a small, deterministic lexical relevance signal in the [0, 1] range."""
    query_terms = terms(query)
    if not query_terms:
        return 0.0
    query_counts = Counter(query_terms)
    text_counts = Counter(terms(text))
    matched = sum(1 for term in query_counts if text_counts[term])
    coverage = matched / len(query_counts)
    frequency = sum(min(text_counts[term], 3) for term in query_counts) / (
        len(query_counts) * 3
    )
    normalized_query = " ".join(query.lower().split())
    normalized_text = " ".join(text.lower().split())
    phrase = float(bool(normalized_query) and normalized_query in normalized_text)
    return 0.7 * coverage + 0.2 * frequency + 0.1 * phrase


def rerank_candidates(
    query: str, candidates: list[RankedCandidate], texts: dict[str, str]
) -> list[tuple[RankedCandidate, float]]:
    """Blend normalized hybrid rank with a bounded lexical baseline."""
    if not candidates:
        return []
    maximum = max(item.retrieval_score for item in candidates) or 1.0
    scored = [
        (
            item,
            0.85 * (item.retrieval_score / maximum)
            + 0.15 * lexical_rerank_score(query, texts.get(item.chunk_id, "")),
        )
        for item in candidates
        if item.chunk_id in texts
    ]
    return sorted(scored, key=lambda item: (-item[1], item[0].chunk_id))


def client() -> QdrantClient:
    return QdrantClient(url=get_settings().qdrant_url, timeout=10)


def ensure_collection(qdrant: QdrantClient | None = None) -> None:
    qdrant = qdrant or client()
    exists = qdrant.collection_exists(COLLECTION)
    if not exists:
        qdrant.create_collection(
            COLLECTION,
            vectors_config={
                "dense": models.VectorParams(
                    size=embedding_provider.dimensions, distance=models.Distance.COSINE
                )
            },
            sparse_vectors_config={
                "sparse": models.SparseVectorParams(index=models.SparseIndexParams(on_disk=False))
            },
        )
    payload_schema = qdrant.get_collection(COLLECTION).payload_schema or {}
    required_indexes = {
        "space_id": models.PayloadSchemaType.KEYWORD,
        "document_id": models.PayloadSchemaType.KEYWORD,
        "file_type": models.PayloadSchemaType.KEYWORD,
        "created_at": models.PayloadSchemaType.DATETIME,
    }
    for field, schema in required_indexes.items():
        if field not in payload_schema:
            qdrant.create_payload_index(COLLECTION, field, schema)


def index_chunks(document: Document, chunks: list[Chunk]) -> None:
    qdrant = client()
    ensure_collection(qdrant)
    points = []
    for chunk in chunks:
        indices, values = embedding_provider.sparse(chunk.text)
        points.append(
            models.PointStruct(
                id=chunk.id,
                vector={
                    "dense": embedding_provider.dense(chunk.text),
                    "sparse": models.SparseVector(indices=indices, values=values),
                },
                payload={
                    "document_id": document.id,
                    "space_id": document.space_id,
                    "filename": document.filename,
                    "file_type": document.filename.rsplit(".", 1)[-1].lower(),
                    "locator": chunk.locator,
                    "text": chunk.text,
                    "created_at": document.created_at.isoformat(),
                },
            )
        )
    if points:
        qdrant.upsert(COLLECTION, points=points, wait=True)


def delete_document_index(document_id: str) -> None:
    qdrant = client()
    if qdrant.collection_exists(COLLECTION):
        qdrant.delete(
            COLLECTION,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="document_id", match=models.MatchValue(value=document_id)
                        )
                    ]
                )
            ),
            wait=True,
        )


def _filters(space_ids: list[str], filters: SearchFilters) -> models.Filter:
    must: list = [models.FieldCondition(key="space_id", match=models.MatchAny(any=space_ids))]
    if filters.document_ids:
        must.append(
            models.FieldCondition(
                key="document_id", match=models.MatchAny(any=filters.document_ids)
            )
        )
    if filters.file_types:
        must.append(
            models.FieldCondition(key="file_type", match=models.MatchAny(any=filters.file_types))
        )
    if filters.created_from or filters.created_to:
        must.append(
            models.FieldCondition(
                key="created_at",
                range=models.DatetimeRange(gte=filters.created_from, lte=filters.created_to),
            )
        )
    return models.Filter(must=must)


def _authorized_space_ids(db: Session, user_id: str) -> list[str]:
    return list(
        db.scalars(
            select(SpaceMembership.space_id).where(SpaceMembership.user_id == user_id)
        )
    )


def _authoritative_candidates(
    db: Session,
    user_id: str,
    candidate_ids: list[str],
    filters: SearchFilters,
) -> dict[str, tuple[Chunk, Document]]:
    if not candidate_ids:
        return {}
    conditions = [
        Chunk.id.in_(candidate_ids),
        SpaceMembership.user_id == user_id,
        Document.status == DocumentStatus.ready,
        Document.deleted_at.is_(None),
    ]
    if filters.document_ids:
        conditions.append(Document.id.in_(filters.document_ids))
    if filters.created_from:
        conditions.append(Document.created_at >= filters.created_from)
    if filters.created_to:
        conditions.append(Document.created_at <= filters.created_to)
    rows = db.execute(
        select(Chunk, Document)
        .join(Document, Chunk.document_id == Document.id)
        .join(
            SpaceMembership,
            and_(
                SpaceMembership.space_id == Document.space_id,
                SpaceMembership.user_id == user_id,
            ),
        )
        .where(*conditions)
    ).all()
    allowed_types = set(filters.file_types)
    return {
        chunk.id: (chunk, document)
        for chunk, document in rows
        if not allowed_types or document.filename.rsplit(".", 1)[-1].lower() in allowed_types
    }


def search_knowledge(
    db: Session,
    user_id: str,
    query: str,
    filters: SearchFilters,
    top_k: int = 10,
) -> list[dict]:
    total_started = perf_counter()
    # PostgreSQL derives authorization before any request reaches the vector index.
    stage_started = perf_counter()
    space_ids = _authorized_space_ids(db, user_id)
    RETRIEVAL_LATENCY.labels("authorize", "success").observe(perf_counter() - stage_started)
    if not space_ids:
        RETRIEVAL_LATENCY.labels("total", "empty").observe(perf_counter() - total_started)
        return []
    qdrant = client()
    ensure_collection(qdrant)
    indices, values = embedding_provider.sparse(query)
    candidate_limit = max(top_k * RETRIEVAL_CANDIDATE_MULTIPLIER, RETRIEVAL_CANDIDATE_FLOOR)
    qdrant_filter = _filters(space_ids, filters)
    stage_started = perf_counter()
    try:
        dense = qdrant.query_points(
            collection_name=COLLECTION,
            query=embedding_provider.dense(query),
            using="dense",
            query_filter=qdrant_filter,
            limit=candidate_limit,
            with_payload=False,
        )
    except Exception:
        RETRIEVAL_LATENCY.labels("dense", "failure").observe(perf_counter() - stage_started)
        RETRIEVAL_LATENCY.labels("total", "failure").observe(perf_counter() - total_started)
        raise
    RETRIEVAL_LATENCY.labels("dense", "success").observe(perf_counter() - stage_started)
    stage_started = perf_counter()
    try:
        sparse = qdrant.query_points(
            collection_name=COLLECTION,
            query=models.SparseVector(indices=indices, values=values),
            using="sparse",
            query_filter=qdrant_filter,
            limit=candidate_limit,
            with_payload=False,
        )
    except Exception:
        RETRIEVAL_LATENCY.labels("sparse", "failure").observe(perf_counter() - stage_started)
        RETRIEVAL_LATENCY.labels("total", "failure").observe(perf_counter() - total_started)
        raise
    RETRIEVAL_LATENCY.labels("sparse", "success").observe(perf_counter() - stage_started)
    fused = reciprocal_rank_fusion(
        [[str(point.id) for point in dense.points], [str(point.id) for point in sparse.points]]
    )
    # Membership and every document filter are checked again from PostgreSQL.
    stage_started = perf_counter()
    authoritative = _authoritative_candidates(
        db, user_id, [item.chunk_id for item in fused], filters
    )
    RETRIEVAL_LATENCY.labels("postgres_recheck", "success").observe(
        perf_counter() - stage_started
    )
    stage_started = perf_counter()
    reranked = rerank_candidates(
        query, fused, {chunk_id: row[0].text for chunk_id, row in authoritative.items()}
    )
    RETRIEVAL_LATENCY.labels("rerank", "success").observe(perf_counter() - stage_started)
    results = []
    for candidate, score in reranked[:top_k]:
        chunk, document = authoritative[candidate.chunk_id]
        results.append(
            {
                "chunk_id": chunk.id,
                "score": score,
                "document_id": document.id,
                "space_id": document.space_id,
                "filename": document.filename,
                "file_type": document.filename.rsplit(".", 1)[-1].lower(),
                "locator": chunk.locator,
                "text": chunk.text,
                "created_at": document.created_at.isoformat(),
            }
        )
    RETRIEVAL_LATENCY.labels("total", "success" if results else "empty").observe(
        perf_counter() - total_started
    )
    return results


def read_chunks(
    db: Session, user_id: str, chunk_ids: list[str], max_words: int = 6000
) -> list[dict]:
    rows = db.execute(
        select(Chunk, Document)
        .join(Document, Chunk.document_id == Document.id)
        .join(
            SpaceMembership,
            and_(
                SpaceMembership.space_id == Document.space_id,
                SpaceMembership.user_id == user_id,
            ),
        )
        .where(
            Chunk.id.in_(chunk_ids),
            SpaceMembership.user_id == user_id,
            Document.status == DocumentStatus.ready,
            Document.deleted_at.is_(None),
        )
    ).all()
    by_id = {chunk.id: (chunk, document) for chunk, document in rows}
    used = 0
    result = []
    for chunk_id in dict.fromkeys(chunk_ids):
        row = by_id.get(chunk_id)
        if not row:
            continue
        chunk, document = row
        count = len(chunk.text.split())
        if used + count > max_words:
            break
        used += count
        result.append(
            {
                "chunk_id": chunk.id,
                "document_id": document.id,
                "filename": document.filename,
                "locator": chunk.locator,
                "text": chunk.text,
            }
        )
    return result
