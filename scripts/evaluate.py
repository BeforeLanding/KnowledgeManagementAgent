"""Run deterministic Week 5 Agent evaluations without external services."""

import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "api"))

from app import search as search_module  # noqa: E402
from app.database import Base  # noqa: E402
from app.evaluation import (  # noqa: E402
    evaluate_gate,
    load_suite_definition,
    public_outcome,
    read_baseline,
    run_evaluation_suite,
    write_baseline,
)
from app.models import (  # noqa: E402
    Chunk,
    Document,
    DocumentStatus,
    EvaluationCase,
    EvaluationSuite,
    KnowledgeSpace,
    SpaceMembership,
    SpaceRole,
    User,
)

SUITE_PATHS = {
    "smoke": ROOT / "evaluations" / "week5-synthetic-regression-v1.json",
    "regression": ROOT / "evaluations" / "week5-synthetic-regression-v1.json",
    "threat": ROOT / "evaluations" / "week6-synthetic-threat-v1.json",
}


class LocalSyntheticQdrant:
    """Small deterministic candidate index; PostgreSQL still makes every access decision."""

    def __init__(self, chunks: list[Chunk]):
        self.chunks = chunks

    def query_points(self, **kwargs):
        query = kwargs["query"]
        scored: list[tuple[str, float]] = []
        for chunk in self.chunks:
            if kwargs["using"] == "dense":
                vector = search_module.embedding_provider.dense(chunk.text)
                score = sum(
                    left * right for left, right in zip(query, vector, strict=True)
                )
            else:
                chunk_indices, chunk_values = search_module.embedding_provider.sparse(chunk.text)
                query_sparse = dict(zip(query.indices, query.values, strict=True))
                score = sum(
                    query_sparse.get(index, 0.0) * value
                    for index, value in zip(chunk_indices, chunk_values, strict=True)
                )
            if score > 0:
                scored.append((chunk.id, score))
        scored.sort(key=lambda item: (-item[1], item[0]))
        return SimpleNamespace(
            points=[SimpleNamespace(id=item[0]) for item in scored[: kwargs["limit"]]]
        )


def build_local_database(profile: str) -> tuple[Session, str, str]:
    suite_path = SUITE_PATHS[profile]
    raw = json.loads(suite_path.read_text(encoding="utf-8"))
    definition = load_suite_definition(suite_path)
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = Session(engine, expire_on_commit=False)
    fixtures = raw["fixtures"]
    for item in fixtures["users"]:
        db.add(
            User(
                id=item["id"],
                email=f"{item['id']}@synthetic.invalid",
                display_name=item["name"],
                password_hash="not-a-real-credential",
            )
        )
    for item in fixtures["spaces"]:
        db.add(KnowledgeSpace(id=item["id"], name=item["name"], description="Synthetic"))
    db.flush()
    for item in fixtures["memberships"]:
        db.add(
            SpaceMembership(
                user_id=item["user_id"],
                space_id=item["space_id"],
                role=SpaceRole(item["role"]),
            )
        )
    chunks: list[Chunk] = []
    for item in fixtures["documents"]:
        document = Document(
            id=item["id"],
            space_id=item["space_id"],
            filename=item["filename"],
            content_type="text/plain",
            size_bytes=sum(len(chunk["text"]) for chunk in item["chunks"]),
            sha256=(item["id"].encode().hex() + "0" * 64)[:64],
            object_key=f"synthetic/{item['id']}",
            status=DocumentStatus(item["status"]),
        )
        db.add(document)
        db.flush()
        for ordinal, item_chunk in enumerate(item["chunks"]):
            chunk = Chunk(
                id=item_chunk["id"],
                document_id=document.id,
                space_id=document.space_id,
                ordinal=ordinal,
                locator=item_chunk["locator"],
                text=item_chunk["text"],
                token_count=len(item_chunk["text"].split()),
            )
            db.add(chunk)
            chunks.append(chunk)
    selected_cases = definition.cases
    if profile == "smoke":
        smoke_ids = {"answer-dispatch", "no-answer", "acl-isolation"}
        selected_cases = [case for case in definition.cases if case.id in smoke_ids]
    db.add(
        EvaluationSuite(
            name=profile,
            version=definition.version,
            description=definition.description,
            data_classification=definition.data_classification,
            configuration=definition.configuration,
        )
    )
    for ordinal, case in enumerate(selected_cases, 1):
        db.add(
            EvaluationCase(
                id=case.id,
                suite=profile,
                version=definition.version,
                query=case.query,
                language=case.language,
                acting_user_id=case.acting_user,
                expected_status=case.expected_status,
                expected_document_ids=[item.document_id for item in case.expected_sources],
                forbidden_document_ids=[item.document_id for item in case.forbidden_sources],
                expected_sources=[item.model_dump() for item in case.expected_sources],
                forbidden_sources=[item.model_dump() for item in case.forbidden_sources],
                required_facts=case.required_facts,
                rubric=case.rubric,
                tags=case.tags,
                ordinal=ordinal,
                is_must_pass=case.must_pass,
            )
        )
    db.commit()
    search_module.client = lambda: LocalSyntheticQdrant(chunks)
    search_module.ensure_collection = lambda _client=None: None
    return db, profile, definition.version


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=tuple(SUITE_PATHS), default="smoke")
    parser.add_argument("--case", help="Run one stable case ID from the selected suite")
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--max-regression", type=float, default=0.02)
    parser.add_argument("--write-baseline", type=Path)
    parser.add_argument("--overwrite-baseline", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        db, suite, version = build_local_database(args.suite)
        with db:
            outcome = run_evaluation_suite(db, suite, version, case_id=args.case)
        payload = public_outcome(outcome)
        if args.write_baseline:
            write_baseline(
                args.write_baseline,
                outcome,
                overwrite=args.overwrite_baseline,
            )
            payload["baseline_written"] = str(args.write_baseline)
        baseline_path = args.baseline
        if baseline_path is None and not args.write_baseline and not args.case:
            candidate = ROOT / "evaluations" / "baselines" / f"{suite}-v1.json"
            baseline_path = candidate if candidate.exists() else None
        if baseline_path:
            gate_passed, failures = evaluate_gate(
                outcome, read_baseline(baseline_path), args.max_regression
            )
            payload["gate_passed"] = gate_passed
            payload["gate_failures"] = failures
        else:
            gate_passed = outcome.passed == outcome.total
            payload["gate_passed"] = gate_passed
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if gate_passed else 1
    except Exception as exc:
        print(json.dumps({"error": type(exc).__name__, "message": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
