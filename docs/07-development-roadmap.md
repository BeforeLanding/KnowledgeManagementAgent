# Development roadmap

- Week 1: repository, Compose, schema, seed identities, ACL and workbench shell.
- Week 2: object storage, all digital parsers, Celery state machine, versioning and deletion.
- Week 3: completed Qdrant dense+sparse candidate retrieval, deterministic RRF, lexical rerank baseline, PostgreSQL-authoritative filters/ACL, retrieval tests and a model-free synthetic benchmark.
- Week 4: bounded LangGraph, provider abstraction, citations, SSE and redacted traces.
- Week 5: evaluation schema, runner, dashboards, synthetic suite and regression gate.
- Week 6: threat tests, 10k-document load test, observability, backups, screenshots and release hardening.

The repository implements the vertical MVP. Remaining hardening work is explicitly tracked in documentation rather than hidden behind demo behaviour. A feature is done only when its contract, authorization rule, error behaviour, tests and operating notes are present.
