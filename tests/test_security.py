from app.providers import EmbeddingProvider
from app.security import hash_password, redact, verify_password


def test_password_hashing():
    encoded = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", encoded)
    assert not verify_password("wrong", encoded)


def test_trace_redaction():
    value = redact("mail jane@example.com phone +65 6123 4567 api_key=supersecret")
    assert "jane@example.com" not in value
    assert "supersecret" not in value


def test_embeddings_are_deterministic_and_bilingual():
    provider = EmbeddingProvider()
    assert provider.dense("物流 shipment") == provider.dense("物流 shipment")
    indices, values = provider.sparse("物流 shipment")
    assert indices and len(indices) == len(values)
