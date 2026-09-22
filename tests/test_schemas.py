import pytest
from app.schemas import SearchRequest
from pydantic import ValidationError


def test_search_contract_caps_top_k():
    with pytest.raises(ValidationError):
        SearchRequest(query="hello", top_k=21)
    assert SearchRequest(query="hello").top_k == 10
