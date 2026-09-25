"""Live classifier check (spec 013 acceptance): requires local Ollama.

    uv run pytest -m "integration and requires_ollama" tests/guardrails/test_intent_live.py
"""

import pytest

from guardrails import GuardrailRejection, screen_query

from .samples import INJECTION, OFF_TOPIC, VALID_INCIDENTS

pytestmark = [pytest.mark.integration, pytest.mark.requires_ollama]


def _passes(text: str) -> bool:
    try:
        screen_query(text)
        return True
    except GuardrailRejection:
        return False


def test_no_valid_incident_is_rejected():
    rejected = [q for q in VALID_INCIDENTS if not _passes(q)]
    assert rejected == []


def test_at_least_95_percent_of_off_topic_and_injection_rejected():
    bad = OFF_TOPIC + INJECTION
    leaked = [q for q in bad if _passes(q)]
    assert len(leaked) <= len(bad) * 0.05, f"leaked: {leaked}"
