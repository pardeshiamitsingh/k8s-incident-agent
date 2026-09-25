import pytest

from guardrails.pii import mask


@pytest.mark.parametrize("text,label,placeholder", [
    ("mail bob@example.com please", "email", "[EMAIL]"),
    ("call 555-123-4567 now", "phone", "[PHONE]"),
    ("call (555) 123-4567 now", "phone", "[PHONE]"),
    ("call +44 20 7946 0958 now", "phone", "[PHONE]"),
    ("card 4111 1111 1111 1111", "card", "[CARD]"),
    ("card 4111111111111111", "card", "[CARD]"),
    ("ssn 123-45-6789", "ssn", "[SSN]"),
    ("jwt eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abc123def", "jwt", "[JWT]"),
    ("key AKIAIOSFODNN7EXAMPLE here", "secret", "[SECRET]"),
    ("Authorization: Bearer abcdefgh12345678", "secret", "Bearer [SECRET]"),
    ("password=hunter2", "secret", "password=[SECRET]"),
    ("api_key: sk-abc123", "secret", "api_key: [SECRET]"),
    ("postgres://user:pass@db:5432/x", "credentials", "postgres://[CREDENTIALS]@db"),
    ("-----BEGIN RSA PRIVATE KEY-----\nMIIabc\n-----END RSA PRIVATE KEY-----", "secret", "[SECRET]"),
])
def test_masks_each_type(text, label, placeholder):
    masked, counts = mask(text)
    assert placeholder in masked
    assert counts.get(label, 0) >= 1


@pytest.mark.parametrize("text", [
    "pod IP 10.96.9.252 port 5432",
    "timestamp 20260925084717 and 2026-09-25T08:47:17Z",
    "version v1.2.3 and image nginx:1.27-alpine",
    "namespace ecommerce pod orders-5c5d674654-nst26",
    "card-like but Luhn invalid 4111 1111 1111 1112",
    "epoch 1758790037123456789",
    "password authentication failed for user shop",
    "secret \"cart-redis-auth-v2\" not found",
    "sha256:" + "ab12cd34" * 8,
])
def test_leaves_incident_data_alone(text):
    masked, counts = mask(text)
    assert masked == text
    assert counts == {}


def test_masking_is_idempotent():
    once, _ = mask("mail bob@example.com password=hunter2")
    twice, counts = mask(once)
    assert once == twice
    assert counts == {}
