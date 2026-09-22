import json

import pytest
from app.load_testing import (
    DATA_CLASSIFICATION,
    generate_documents,
    run_local_microbenchmark,
    validate_limits,
)


def test_synthetic_generator_is_repeatable_company_neutral_and_bounded():
    first = generate_documents(3, seed=42)
    second = generate_documents(3, seed=42)
    assert first == second
    assert len({item.id for item in first}) == 3
    assert all("synthetic" in item.text.lower() for item in first)
    assert "credential" not in json.dumps([item.text for item in first]).lower()
    with pytest.raises(ValueError):
        generate_documents(10_001)


def test_load_limits_reject_unsafe_scale_concurrency_requests_and_duration():
    for values in (
        (10_001, 1, 1, 1),
        (1, 33, 1, 1),
        (1, 1, 100_001, 1),
        (1, 1, 1, 3_601),
    ):
        with pytest.raises(ValueError):
            validate_limits(*values)


def test_small_local_microbenchmark_reports_only_actual_local_measurements():
    result = run_local_microbenchmark(
        documents=12,
        concurrency=2,
        requests=20,
        seed=606,
        duration_seconds=10,
    )
    assert result["data_classification"] == DATA_CLASSIFICATION
    assert result["scope"]["documents"] == 12
    assert result["measurements"]["index"]["entries"] == 12
    assert result["measurements"]["retrieval"]["p95_ms"] is not None
    assert result["measurements"]["resource"]["tracemalloc_peak_bytes"] > 0
    assert any("not a Compose" in item for item in result["limitations"])
