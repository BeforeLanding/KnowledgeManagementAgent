from qdrant_client import QdrantClient, models
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .models import Chunk, Document, DocumentStatus
from .providers import embedding_provider, terms
from .schemas import SearchFilters

COLLECTION = "knowledge_chunks"


def client() -> QdrantClient:
    return QdrantClient(url=get_settings().qdrant_url, timeout=10)


def ensure_collection(qdrant: QdrantClient | None = None) -> None:
    qdrant = qdrant or client()
    if not qdrant.collection_exists(COLLECTION):
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
        for field in ("space_id", "document_id", "file_type"):
            qdrant.create_payload_index(COLLECTION, field, models.PayloadSchemaType.KEYWORD)


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


def search_knowledge(
    db: Session,
    query: str,
    space_ids: list[str],
    filters: SearchFilters,
    top_k: int = 10,
) -> list[dict]:
    if not space_ids:
        return []
    qdrant = client()
    ensure_collection(qdrant)
    indices, values = embedding_provider.sparse(query)
    result = qdrant.query_points(
        collection_name=COLLECTION,
        prefetch=[
            models.Prefetch(
                query=embedding_provider.dense(query),
                using="dense",
                limit=max(top_k * 3, 20),
                filter=_filters(space_ids, filters),
            ),
            models.Prefetch(
                query=models.SparseVector(indices=indices, values=values),
                using="sparse",
                limit=max(top_k * 3, 20),
                filter=_filters(space_ids, filters),
            ),
        ],
        query=models.FusionQuery(fusion=models.Fusion.RRF),
        # Fetch extra candidates because PostgreSQL is authoritative and may
        # reject stale Qdrant points left behind by an asynchronous purge.
        limit=max(top_k * 3, 20),
        with_payload=True,
    )
    query_terms = set(terms(query))
    candidate_ids = [str(point.id) for point in result.points]
    visible_ids = set(
        db.scalars(
            select(Chunk.id)
            .join(Document, Chunk.document_id == Document.id)
            .where(
                Chunk.id.in_(candidate_ids),
                Chunk.space_id.in_(space_ids),
                Document.status == DocumentStatus.ready,
                Document.deleted_at.is_(None),
            )
        )
    )
    items = []
    for point in result.points:
        if str(point.id) not in visible_ids:
            continue
        payload = point.payload or {}
        lexical_overlap = len(query_terms.intersection(terms(str(payload.get("text", "")))))
        items.append(
            {
                "chunk_id": str(point.id),
                "score": float(point.score) + lexical_overlap * 0.001,
                **payload,
            }
        )
    return sorted(items, key=lambda item: item["score"], reverse=True)[:top_k]


def read_chunks(
    db: Session, chunk_ids: list[str], space_ids: list[str], max_words: int = 6000
) -> list[dict]:
    rows = db.execute(
        select(Chunk, Document)
        .join(Document, Chunk.document_id == Document.id)
        .where(
            Chunk.id.in_(chunk_ids),
            Chunk.space_id.in_(space_ids),
            Document.status == DocumentStatus.ready,
            Document.deleted_at.is_(None),
        )
    ).all()
    used = 0
    result = []
    for chunk, document in rows:
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
