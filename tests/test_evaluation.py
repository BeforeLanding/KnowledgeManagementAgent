from pathlib import Path

import pytest
from app.evaluation import evaluate_synthetic_suite, ndcg_at_k, recall_at_k, reciprocal_rank


def test_retrieval_metrics_have_standard_binary_relevance_semantics():
    retrieved = ["noise", "relevant-a", "relevant-b"]
    relevant = {"relevant-a", "relevant-b"}

    assert recall_at_k(retrieved, relevant, 2) == 0.5
    assert reciprocal_rank(retrieved, relevant) == 0.5
    assert ndcg_at_k(retrieved, relevant, 3) == pytest.approx(0.6934264036)


def test_synthetic_retrieval_suite_is_repeatable_and_meets_week3_baseline():
    path = Path("evaluations/week3-synthetic-retrieval.json")

    first = evaluate_synthetic_suite(path)
    second = evaluate_synthetic_suite(path)

    assert first == second
    assert first["suite"] == "week3-synthetic-retrieval-v1"
    assert first["cases"] == 5
    assert first["recall@5"] >= 0.9
    assert first["mrr"] >= 0.8
    assert first["ndcg@5"] >= 0.85
