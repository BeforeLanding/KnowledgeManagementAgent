import json
import math
from collections.abc import Sequence
from pathlib import Path

from .providers import embedding_provider
from .search import reciprocal_rank_fusion, rerank_candidates


def recall_at_k(retrieved: Sequence[str], relevant: set[str], k: int) -> float:
    if not relevant:
        return 0.0
    return len(set(retrieved[:k]).intersection(relevant)) / len(relevant)


def reciprocal_rank(retrieved: Sequence[str], relevant: set[str]) -> float:
    return next(
        (1.0 / rank for rank, item in enumerate(retrieved, start=1) if item in relevant),
        0.0,
    )


def ndcg_at_k(retrieved: Sequence[str], relevant: set[str], k: int) -> float:
    if not relevant:
        return 0.0
    dcg = sum(
        1.0 / math.log2(rank + 1)
        for rank, item in enumerate(retrieved[:k], start=1)
        if item in relevant
    )
    ideal = sum(1.0 / math.log2(rank + 1) for rank in range(1, min(k, len(relevant)) + 1))
    return dcg / ideal


def _dot(left: Sequence[float], right: Sequence[float]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=True))


def _offline_search(query: str, documents: list[dict], top_k: int) -> list[str]:
    query_dense = embedding_provider.dense(query)
    query_sparse_indices, query_sparse_values = embedding_provider.sparse(query)
    query_sparse = dict(zip(query_sparse_indices, query_sparse_values, strict=True))
    dense_scores: list[tuple[str, float]] = []
    sparse_scores: list[tuple[str, float]] = []
    texts: dict[str, str] = {}
    for document in documents:
        document_id = str(document["id"])
        text = str(document["text"])
        texts[document_id] = text
        dense_scores.append((document_id, _dot(query_dense, embedding_provider.dense(text))))
        indices, values = embedding_provider.sparse(text)
        sparse_scores.append(
            (
                document_id,
                sum(
                    query_sparse.get(index, 0.0) * value
                    for index, value in zip(indices, values, strict=True)
                ),
            )
        )
    dense_rank = [item[0] for item in sorted(dense_scores, key=lambda item: (-item[1], item[0]))]
    sparse_rank = [
        item[0] for item in sorted(sparse_scores, key=lambda item: (-item[1], item[0]))
    ]
    fused = reciprocal_rank_fusion([dense_rank, sparse_rank])
    return [item.chunk_id for item, _score in rerank_candidates(query, fused, texts)[:top_k]]


def evaluate_synthetic_suite(path: Path, top_k: int = 5) -> dict[str, float | int | str]:
    suite = json.loads(path.read_text(encoding="utf-8"))
    documents = suite["documents"]
    cases = suite["cases"]
    recalls = []
    reciprocal_ranks = []
    ndcgs = []
    for case in cases:
        relevant = set(case["relevant_document_ids"])
        retrieved = _offline_search(case["query"], documents, top_k)
        recalls.append(recall_at_k(retrieved, relevant, top_k))
        reciprocal_ranks.append(reciprocal_rank(retrieved, relevant))
        ndcgs.append(ndcg_at_k(retrieved, relevant, top_k))
    count = len(cases)
    return {
        "suite": str(suite["name"]),
        "cases": count,
        f"recall@{top_k}": sum(recalls) / count if count else 0.0,
        "mrr": sum(reciprocal_ranks) / count if count else 0.0,
        f"ndcg@{top_k}": sum(ndcgs) / count if count else 0.0,
    }
