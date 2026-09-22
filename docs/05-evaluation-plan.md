# Evaluation plan

The full synthetic suite targets 150 cases: 35 single-document, 25 cross-document, 20 exact identifiers, 20 bilingual, 15 no-answer, 10 conflicts, 15 ACL attacks, and 10 prompt-injection cases. JSONL import/export uses query, language, acting user, expected and forbidden sources, required facts, rubric, tags and expected status.

Retrieval reports Recall@K, MRR and nDCG. Deterministic answer checks validate schema, citations, required facts, refusal and forbidden-source leakage. A configured LLM judge may score correctness, completeness and groundedness but cannot gate releases until it reaches 80% agreement with a 30-case double-human-labelled calibration set.

ACL, injection and must-pass cases require 100%. Other core metrics cannot regress by more than two percentage points from the accepted baseline. Every production-like defect is first captured as a failing case, tagged with root cause, then retained permanently.

The committed Smoke and Regression profiles are built from
`evaluations/week5-synthetic-regression-v1.json`, which is explicitly labelled
`synthetic-company-neutral`. Cases contain query, language, a server-resolved acting-user key,
expected status, expected/forbidden document and optional chunk sources, required facts, rubric,
tags and a must-pass flag. Suite configuration records prompt, model, provider, embedding,
chunking, retrieval and code versions. PostgreSQL persists the trusted runtime mapping and remains
authoritative for users, memberships, document lifecycle and citation fields.

The deterministic Runner invokes the existing bounded Agent with the Fake Provider. It reports
Recall@5, MRR, nDCG@5, status/refusal accuracy, required-fact coverage, citation accuracy and
completeness, forbidden-source safety, ACL isolation, conflict preservation and prompt-injection
safety. Citation validation compares the exact document ID, chunk ID, filename, locator and
snippet against a ready, non-deleted, currently authorized PostgreSQL row. Cases are isolated,
sorted by ordinal and ID, and a case exception cannot abort the suite.

Run the gates with:

```bash
uv run python scripts/evaluate.py --suite smoke
uv run python scripts/evaluate.py --suite regression
uv run python scripts/evaluate.py --suite regression --case prompt-injection
```

The checked-in versioned baselines live under `evaluations/baselines/`. Core metrics may fall by
at most 0.02; any ACL, prompt-injection or must-pass case failure fails the Gate. A normal run never
rewrites a baseline. Updating one requires the explicit `--write-baseline PATH` option and
`--overwrite-baseline` for an existing file, followed by human review of the diff. Exit codes are
0 for pass, 1 for regression and 2 for invalid input/runtime failure.

The Week 3 retrieval-only benchmark remains available through
`scripts/evaluate_retrieval.py`. A configured LLM judge is still optional design space only: it
is not implemented or used by the default Gate, and must not gate releases before the documented
human calibration threshold is met.
