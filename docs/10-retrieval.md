# Retrieval

## Pipeline

1. The API passes the authenticated user ID, query, filters and top-k to the retrieval service. Public requests and model tool calls never supply space IDs.
2. PostgreSQL resolves current space memberships. An empty membership set returns no results without calling Qdrant.
3. Qdrant executes separate dense and sparse nearest-neighbour queries with identical authorized-space, document, date and normalized file-type payload filters. Each branch retrieves up to `max(4 × top-k, 20)` candidates.
4. The API fuses the two ordered chunk-ID lists with reciprocal rank fusion: each occurrence contributes `1 / (60 + rank)`. Duplicate IDs inside one branch count once and deterministic first-seen/chunk-ID tie breaks make tests repeatable.
5. PostgreSQL fetches candidate chunks while joining the user's current memberships and ready, non-deleted documents. It reapplies document and date filters and derives file type from the authoritative filename. Qdrant payload text and metadata are ignored.
6. A lightweight reranker blends 85% normalized RRF score with 15% lexical score. The lexical score combines unique-query-term coverage, capped term frequency and exact normalized phrase presence. This baseline is bounded, deterministic, bilingual at the existing tokenizer level and requires no paid model.
7. `read_chunks` repeats the membership and document-visibility join and preserves requested rank order subject to the context budget.

## Filter semantics

`document_ids` are de-duplicated after trimming. `file_types` are case-insensitive and accept either `pdf` or `.PDF`; stored comparison uses the final filename suffix. `created_from` and `created_to` are inclusive and an inverted range is rejected during request validation. Qdrant filters improve recall latency but never decide authorization or final visibility.

## Failure and consistency behavior

If Qdrant is unavailable, search fails as an infrastructure error; it does not fall back to an unbounded PostgreSQL text scan. If Qdrant contains stale or malicious payload, only candidate chunk IDs are considered and PostgreSQL content wins. A membership revoked between candidate retrieval and response construction is rejected by the second database join. Deleted or non-ready documents are likewise invisible before physical vector purge.

## Verification

Unit tests use in-memory SQLite and fake Qdrant responses, so no PostgreSQL, Qdrant, MinIO, OpenAI or other paid service is needed. The fixed synthetic benchmark reports Recall@K, MRR and binary-relevance nDCG and can be run with `uv run python scripts/evaluate_retrieval.py`.

Week 6 threat tests additionally feed forged payload content, filenames, document IDs and space IDs
from a fake Qdrant response. `with_payload=False` and the PostgreSQL join ensure only the candidate
point ID has influence. Retrieval stage histograms use the bounded labels `authorize`, `dense`,
`sparse`, `postgres_recheck`, `rerank` and `total`.
