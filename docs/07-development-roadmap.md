# Development roadmap

- Week 1: repository, Compose, schema, seed identities, ACL and workbench shell.
- Week 2: object storage, all digital parsers, Celery state machine, versioning and deletion.
- Week 3: completed Qdrant dense+sparse candidate retrieval, deterministic RRF, lexical rerank baseline, PostgreSQL-authoritative filters/ACL, retrieval tests and a model-free synthetic benchmark.
- Week 4: completed explicit bounded LangGraph, deterministic and OpenAI-compatible Providers, authorized citations, incremental SSE, evidence refusal/conflict handling and redacted user-isolated traces.
- Week 5: completed versioned evaluation schema, isolated deterministic Agent runner, synthetic
  smoke/regression suites, citation/ACL/injection metrics, versioned baseline Gate, bounded APIs
  and a lightweight evaluation view.
- Week 6: threat tests, 10k-document load test, observability, backups, screenshots and release hardening.

The repository implements the vertical MVP. Remaining hardening work is explicitly tracked in documentation rather than hidden behind demo behaviour. A feature is done only when its contract, authorization rule, error behaviour, tests and operating notes are present.
