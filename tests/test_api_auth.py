import pytest
from fastapi import HTTPException

from api.auth import get_expected_token, require_bearer_token


def test_get_expected_token_reads_env(monkeypatch):
    monkeypatch.setenv("INCIDENT_AGENT_API_TOKEN", "secret123")
    assert get_expected_token() == "secret123"


def test_get_expected_token_missing_raises(monkeypatch):
    monkeypatch.delenv("INCIDENT_AGENT_API_TOKEN", raising=False)
    with pytest.raises(RuntimeError):
        get_expected_token()


def test_require_bearer_token_accepts_matching_token(monkeypatch):
    monkeypatch.setenv("INCIDENT_AGENT_API_TOKEN", "secret123")
    require_bearer_token(authorization="Bearer secret123")  # no raise


def test_require_bearer_token_rejects_missing_header(monkeypatch):
    monkeypatch.setenv("INCIDENT_AGENT_API_TOKEN", "secret123")
    with pytest.raises(HTTPException) as exc_info:
        require_bearer_token(authorization=None)
    assert exc_info.value.status_code == 401


def test_require_bearer_token_rejects_wrong_token(monkeypatch):
    monkeypatch.setenv("INCIDENT_AGENT_API_TOKEN", "secret123")
    with pytest.raises(HTTPException) as exc_info:
        require_bearer_token(authorization="Bearer wrong")
    assert exc_info.value.status_code == 401


def test_require_bearer_token_rejects_non_bearer_scheme(monkeypatch):
    monkeypatch.setenv("INCIDENT_AGENT_API_TOKEN", "secret123")
    with pytest.raises(HTTPException) as exc_info:
        require_bearer_token(authorization="Basic secret123")
    assert exc_info.value.status_code == 401
