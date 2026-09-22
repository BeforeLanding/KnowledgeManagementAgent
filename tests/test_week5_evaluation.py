import json
from pathlib import Path

import pytest
from app.database import Base
from app.evaluation import (
    CaseOutcome,
    SuiteOutcome,
    evaluate_case_response,
    evaluate_gate,
    load_suite_definition,
    run_evaluation_suite,
    write_baseline,
)
from app.models import (
    Chunk,
    Document,
    DocumentStatus,
    EvaluationCase,
    KnowledgeSpace,
    SpaceMembership,
    SpaceRole,
    User,
)
from app.routes import evaluation_cases
from app.schemas import ChatResponse, Citation, EvaluationSuiteDefinition
from app.security import create_token
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool


def make_db() -> tuple[Session, User, KnowledgeSpace]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = Session(engine, expire_on_commit=False)
    user = User(
        id="eval-user",
        email="eval@synthetic.invalid",
        display_name="Eval",
        password_hash="x",
    )
    space = KnowledgeSpace(id="eval-space", name="Evaluation Synthetic")
    db.add_all([user, space])
    db.flush()
    db.add(SpaceMembership(user_id=user.id, space_id=space.id, role=SpaceRole.viewer))
    db.commit()
    return db, user, space


def test_suite_schema_requires_company_neutral_data_configuration_and_unique_cases():
    valid = load_suite_definition(Path("evaluations/week5-synthetic-regression-v1.json"))
    assert valid.data_classification == "synthetic-company-neutral"
    assert valid.configuration["provider"] == "fake"

    payload = valid.model_dump()
    payload["data_classification"] = "internal-real-data"
    with pytest.raises(ValidationError):
        EvaluationSuiteDefinition.model_validate(payload)
    payload = valid.model_dump()
    payload["cases"] = [payload["cases"][0], payload["cases"][0]]
    with pytest.raises(ValidationError):
        EvaluationSuiteDefinition.model_validate(payload)


def test_citation_validation_checks_all_fields_and_postgres_visibility():
    db, user, space = make_db()
    document = Document(
        id="visible-doc",
        space_id=space.id,
        filename="synthetic.txt",
        content_type="text/plain",
        size_bytes=20,
        sha256="a" * 64,
        object_key="synthetic/visible",
        status=DocumentStatus.ready,
    )
    db.add(document)
    db.flush()
    chunk = Chunk(
        id="visible-chunk",
        document_id=document.id,
        space_id=space.id,
        ordinal=0,
        locator="line 2",
        text="Synthetic fact is GREEN.",
        token_count=4,
    )
    db.add(chunk)
    case = EvaluationCase(
        id="citation-case",
        suite="regression",
        version="1",
        query="fact",
        acting_user_id=user.id,
        expected_sources=[{"document_id": document.id, "chunk_id": chunk.id}],
        expected_document_ids=[document.id],
        required_facts=["GREEN"],
    )
    db.add(case)
    db.commit()
    response = ChatResponse(
        status="answered",
        answer="The synthetic fact is GREEN.",
        trace_id="trace",
        citations=[
            Citation(
                document_id=document.id,
                chunk_id=chunk.id,
                filename=document.filename,
                locator=chunk.locator,
                snippet=chunk.text[:300],
            )
        ],
    )

    passed, metrics, _summary = evaluate_case_response(db, case, user.id, response)
    assert passed
    assert metrics["citation_accuracy"] == 1.0

    response.citations[0].locator = "forged locator"
    passed, metrics, _summary = evaluate_case_response(db, case, user.id, response)
    assert not passed
    assert metrics["citation_accuracy"] == 0.0

    document.status = DocumentStatus.deleted
    db.commit()
    response.citations[0].locator = chunk.locator
    _passed, metrics, _summary = evaluate_case_response(db, case, user.id, response)
    assert metrics["acl_isolation"] == 0.0
    db.close()


def test_runner_isolates_case_errors_and_sorts_results(monkeypatch):
    db, user, _space = make_db()
    db.add_all(
        [
            EvaluationCase(
                id="later-failure",
                suite="regression",
                version="1",
                query="fail",
                acting_user_id=user.id,
                ordinal=2,
            ),
            EvaluationCase(
                id="first-success",
                suite="regression",
                version="1",
                query="pass",
                acting_user_id=user.id,
                ordinal=1,
            ),
        ]
    )
    db.commit()

    def fake_run(_db, _user_id, query, _filters, provider):
        del provider
        if query == "fail":
            raise RuntimeError("token=must-not-persist")
        return ChatResponse(status="answered", answer="ok", citations=[], trace_id="safe")

    monkeypatch.setattr("app.evaluation.run_agent", fake_run)
    outcome = run_evaluation_suite(db, "regression", "1")

    assert [item.case_id for item in outcome.results] == ["first-success", "later-failure"]
    assert outcome.results[0].passed
    assert outcome.results[1].error_category == "RUNTIMEERROR"
    assert "must-not-persist" not in outcome.results[1].safe_summary

    single = run_evaluation_suite(db, "regression", "1", case_id="first-success")
    assert [item.case_id for item in single.results] == ["first-success"]
    db.close()


def test_gate_has_two_point_tolerance_and_zero_tolerance_tags():
    good = CaseOutcome("normal", 1, True, "answered", 1, None, {}, "passed", [])
    outcome = SuiteOutcome(
        "regression", "1", 1, 1, {"case_pass_rate": 0.981}, [good]
    )
    passed, failures = evaluate_gate(outcome, {"metrics": {"case_pass_rate": 1.0}})
    assert passed and not failures

    bad_acl = CaseOutcome(
        "acl-case", 1, False, "failed", 1, "ERROR", {}, "failed", ["acl"]
    )
    outcome = SuiteOutcome(
        "regression", "1", 1, 0, {"case_pass_rate": 0.99}, [bad_acl]
    )
    passed, failures = evaluate_gate(outcome, {"metrics": {"case_pass_rate": 1.0}})
    assert not passed
    assert failures == ["zero-tolerance case failed: acl-case"]


def test_baseline_requires_explicit_overwrite(tmp_path):
    outcome = SuiteOutcome("smoke", "1", 0, 0, {"case_pass_rate": 1.0}, [])
    path = tmp_path / "baseline.json"
    write_baseline(path, outcome)
    assert json.loads(path.read_text())["data_classification"] == "synthetic-company-neutral"
    with pytest.raises(FileExistsError):
        write_baseline(path, outcome)


def test_evaluation_case_definitions_are_admin_only():
    db, viewer, _space = make_db()
    with pytest.raises(HTTPException) as denied:
        evaluation_cases(viewer, db)
    assert denied.value.status_code == 403

    membership = db.query(SpaceMembership).filter_by(user_id=viewer.id).one()
    membership.role = SpaceRole.admin
    db.commit()
    assert evaluation_cases(viewer, db) == []
    db.close()


def test_evaluation_api_requires_authentication_and_uses_error_contract():
    from app.database import get_db
    from app.main import app

    db, user, _space = make_db()

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(app)
        denied = client.get("/api/v1/evaluations/suites")
        assert denied.status_code == 401
        assert set(denied.json()) == {"code", "message", "retryable", "trace_id"}

        allowed = client.get(
            "/api/v1/evaluations/suites",
            headers={"Authorization": f"Bearer {create_token(user.id)}"},
        )
        assert allowed.status_code == 200
        assert allowed.json() == []
    finally:
        app.dependency_overrides.clear()
        db.close()
