# Evaluation plan

The full synthetic suite targets 150 cases: 35 single-document, 25 cross-document, 20 exact identifiers, 20 bilingual, 15 no-answer, 10 conflicts, 15 ACL attacks, and 10 prompt-injection cases. JSONL import/export uses query, language, acting user, expected and forbidden sources, required facts, rubric, tags and expected status.

Retrieval reports Recall@K, MRR and nDCG. Deterministic answer checks validate schema, citations, required facts, refusal and forbidden-source leakage. A configured LLM judge may score correctness, completeness and groundedness but cannot gate releases until it reaches 80% agreement with a 30-case double-human-labelled calibration set.

ACL, injection and must-pass cases require 100%. Other core metrics cannot regress by more than two percentage points from the accepted baseline. Every production-like defect is first captured as a failing case, tagged with root cause, then retained permanently.

The committed Smoke suite is intentionally model-free. A larger suite is populated after synthetic documents receive stable IDs, then versioned with prompt, model, embedding, chunking and retrieval configuration.

