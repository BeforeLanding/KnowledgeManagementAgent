# Evaluation plan

The full synthetic suite targets 150 cases: 35 single-document, 25 cross-document, 20 exact identifiers, 20 bilingual, 15 no-answer, 10 conflicts, 15 ACL attacks, and 10 prompt-injection cases. JSONL import/export uses query, language, acting user, expected and forbidden sources, required facts, rubric, tags and expected status.

Retrieval reports Recall@K, MRR and nDCG. Deterministic answer checks validate schema, citations, required facts, refusal and forbidden-source leakage. A configured LLM judge may score correctness, completeness and groundedness but cannot gate releases until it reaches 80% agreement with a 30-case double-human-labelled calibration set.

ACL, injection and must-pass cases require 100%. Other core metrics cannot regress by more than two percentage points from the accepted baseline. Every production-like defect is first captured as a failing case, tagged with root cause, then retained permanently.

The committed Smoke suite is intentionally model-free. The Week 3 retrieval suite in `evaluations/week3-synthetic-retrieval.json` is also explicitly company-neutral synthetic data. It uses deterministic local hashed dense and sparse vectors, the production RRF and rerank functions, and reports macro-average Recall@5, MRR and nDCG@5. Run it with:

```bash
uv run python scripts/evaluate_retrieval.py
```

The small suite is a repeatable engineering regression check, not a claim about production quality. Its checked-in baseline is Recall@5 ≥ 0.90, MRR ≥ 0.80 and nDCG@5 ≥ 0.85. A larger suite is populated after synthetic documents receive stable IDs, then versioned with prompt, model, embedding, chunking and retrieval configuration.
