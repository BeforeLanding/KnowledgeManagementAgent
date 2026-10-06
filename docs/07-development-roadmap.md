# Development roadmap

- Week 1: repository, Compose, schema, seed identities, ACL and workbench shell.
- Week 2: object storage, all digital parsers, Celery state machine, versioning and deletion.
- Week 3: completed Qdrant dense+sparse candidate retrieval, deterministic RRF, lexical rerank baseline, PostgreSQL-authoritative filters/ACL, retrieval tests and a model-free synthetic benchmark.
- Week 4: completed explicit bounded LangGraph, deterministic and OpenAI-compatible Providers, authorized citations, incremental SSE, evidence refusal/conflict handling and redacted user-isolated traces.
- Week 5: completed versioned evaluation schema, isolated deterministic Agent runner, synthetic
  smoke/regression suites, citation/ACL/injection metrics, versioned baseline Gate, bounded APIs
  and a lightweight evaluation view.
- Week 6: completed deterministic threat tests and zero-tolerance Gate; bounded 10k-capable
  synthetic/load tooling; low-cardinality observability, readiness and alert rules; dry-run-safe
  backup/restore/reconciliation operations; lightweight release status UI; and Compose/release
  hardening. The 10k and Compose workloads are opt-in and no unexecuted capacity result is claimed.

The repository implements the vertical MVP. Remaining hardening work is explicitly tracked in documentation rather than hidden behind demo behaviour. A feature is done only when its contract, authorization rule, error behaviour, tests and operating notes are present.

## Next phase: internship evidence

The Week 1–6 entries describe the implemented prototype surface, not verified production capacity
or live-model answer quality. Dense retrieval currently uses term hashing, evidence sufficiency
checks only for nonempty context, and citations identify authorized sources rather than validate
each answer claim. The default evaluation runner uses the Fake Provider; Web tests are type checks.

For AI application / Agent backend internship preparation, follow the
[optimization plan](13-internship-optimization-plan.zh.md) and
[execution checklist](14-internship-execution-checklist.zh.md):

1. KM-00–KM-03: establish a reproducible baseline, labelled dev/test corpus, real embeddings,
   tokenizer-based chunking, and retrieval comparisons with explicit metric definitions.
2. KM-04–KM-05: add evidence decisions and source/claim validation, then publish a bounded
   live-model report with human labels, failures, latency, usage and limitations.
3. KM-06–KM-08: reproduce concurrent ingestion/deletion failure windows, complete session and
   deployment workflows, and verify them with PostgreSQL and deployed service/E2E tests.
4. KM-09: publish reproducible reports and a short synthetic-data demonstration; use only
   measured, traceable results in resume claims.

All KM tasks begin unverified. A planned result, a deterministic fixture pass, and a deployed
measurement are different evidence; keep their labels and artifacts distinct when marking work done.
