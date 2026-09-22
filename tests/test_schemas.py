from datetime import UTC, datetime

import pytest
from app.schemas import SearchFilters, SearchRequest
from pydantic import ValidationError


def test_search_contract_caps_top_k():
    with pytest.raises(ValidationError):
        SearchRequest(query="hello", top_k=21)
    assert SearchRequest(query="hello").top_k == 10


def test_search_filters_are_normalized_and_date_range_is_validated():
    filters = SearchFilters(
        document_ids=[" doc-1 ", "doc-1", ""], file_types=[".PDF", "pdf", " TXT "]
    )
    assert filters.document_ids == ["doc-1"]
    assert filters.file_types == ["pdf", "txt"]

    with pytest.raises(ValidationError):
        SearchFilters(
            created_from=datetime(2026, 2, 1, tzinfo=UTC),
            created_to=datetime(2026, 1, 1, tzinfo=UTC),
        )
