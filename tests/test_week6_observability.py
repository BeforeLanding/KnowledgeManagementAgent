import pytest
from app.config import Settings
from app.database import Base
from app.health import readiness_report
from app.main import app
from app.models import User
from app.observability import bounded
from app.routes import operations_status
from fastapi.testclient import TestClient
from prometheus_client import generate_latest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


def test_metric_names_and_labels_are_bounded_and_content_free():
    assert bounded("suite", "attacker-controlled-suite-id") == "other"
    assert bounded("security", "authorization") == "authorization"
    rendered = generate_latest().decode()
    for name in (
        "kma_ingestion_transitions_total",
        "kma_queue_events_total",
        "kma_retrieval_stage_seconds",
        "kma_agent_node_seconds",
        "kma_provider_requests_total",
        "kma_evaluation_gate_total",
        "kma_agent_refusals_total",
        "kma_citations_total",
        "kma_security_failures_total",
        "kma_dependency_ready",
    ):
        assert name in rendered
    for forbidden in ("query=", "answer=", "filename=", "email=", "api_key=", "trace_id="):
        assert forbidden not in rendered.lower()


def test_http_metric_uses_route_template_not_high_cardinality_path():
    marker = "synthetic-run-id-that-must-not-be-a-label"
    response = TestClient(app).get(f"/api/v1/evaluations/runs/{marker}")
    assert response.status_code == 401
    rendered = generate_latest().decode()
    assert marker not in rendered
    assert '/api/v1/evaluations/runs/{run_id}' in rendered


def test_readiness_distinguishes_dependency_failure_without_error_details():
    def fail() -> None:
        raise RuntimeError("token=synthetic-sensitive-detail")

    report = readiness_report({"postgres": lambda: None, "redis": fail})
    assert report["status"] == "not_ready"
    assert report["components"]["postgres"]["ready"] is True
    assert report["components"]["redis"] == {
        "ready": False,
        "latency_ms": report["components"]["redis"]["latency_ms"],
        "code": "UNAVAILABLE",
    }
    assert "synthetic-sensitive-detail" not in str(report)


def test_operations_status_is_small_redacted_and_postgres_authoritative(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(email="ops@synthetic.invalid", display_name="Ops", password_hash="x")
        db.add(user)
        db.commit()
        monkeypatch.setattr(
            "app.routes.readiness_report",
            lambda: {"status": "ready", "components": {"postgres": {"ready": True}}},
        )
        result = operations_status(user, db)
    assert result["readiness"]["status"] == "ready"
    assert result["security_summary"]["postgres_authoritative"] is True
    assert result["security_summary"]["details_redacted"] is True
    assert "topology" not in result


def test_production_configuration_rejects_defaults_and_accepts_explicit_secrets():
    with pytest.raises(ValueError, match="unsafe production configuration"):
        Settings(_env_file=None, app_env="production")
    settings = Settings(
        _env_file=None,
        app_env="production",
        jwt_secret="a-production-only-secret-with-32-chars",
        minio_access_key="production-access",
        minio_secret_key="production-secret-value",
        seed_demo_data=False,
        model_provider="openai",
        openai_base_url="https://models.synthetic.invalid/v1",
        openai_api_key="runtime-only-synthetic-key",
        chat_model="synthetic-configured-model",
    )
    assert settings.seed_demo_data is False
