"""The screening pipeline (spec 013).

Order for a query: normalise + limit -> mask PII/secrets -> injection
patterns -> local-LLM intent classification (fail closed). Masking runs
before pattern matching and the classifier, so neither sees raw secrets,
and before any LLM or LangSmith call.
"""

import logging

from . import audit
from .injection import find_injection
from .intent import classify_intent
from .models import ScreenedText
from .normalize import NOTES_MAX_CHARS, POSTMORTEM_MAX_CHARS, QUERY_MAX_CHARS, normalize
from .pii import mask

logger = logging.getLogger(__name__)

_MESSAGES = {
    "too_long": "The text is too long. Shorten it and try again.",
    "empty": "The text is empty.",
    "injection": "This looks like an attempt to change the tool's instructions, so it was rejected.",
    "off_topic": "This doesn't look like a Kubernetes incident report. Describe what is broken.",
    "screening_unavailable": "Input screening is temporarily unavailable. Try again shortly.",
}


class GuardrailRejection(Exception):
    def __init__(self, reason: str, status_code: int = 422):
        self.reason = reason
        self.status_code = status_code
        self.message = _MESSAGES[reason]
        super().__init__(f"{reason}: {self.message}")


def _screen_common(text: str, endpoint: str, max_chars: int) -> ScreenedText:
    if len(text) > max_chars * 2:  # cheap check before doing any work on huge input
        audit.log_rejection(endpoint, "too_long", text)
        raise GuardrailRejection("too_long")

    normalized = normalize(text)
    if not normalized:
        audit.log_rejection(endpoint, "empty", text)
        raise GuardrailRejection("empty")
    if len(normalized) > max_chars:
        audit.log_rejection(endpoint, "too_long", text)
        raise GuardrailRejection("too_long")

    masked, redactions = mask(normalized)
    audit.log_redactions(endpoint, redactions)

    pattern = find_injection(masked)
    if pattern:
        audit.log_rejection(endpoint, "injection", text, pattern)
        raise GuardrailRejection("injection")

    return ScreenedText(text=masked, redactions=redactions)


def screen_query(text: str, endpoint: str = "/diagnose/query") -> ScreenedText:
    screened = _screen_common(text, endpoint, QUERY_MAX_CHARS)

    try:
        verdict = classify_intent(screened.text)
    except Exception:
        logger.exception("intent classification failed; failing closed")
        audit.log_rejection(endpoint, "screening_unavailable", text)
        raise GuardrailRejection("screening_unavailable", status_code=503)

    if verdict.label != "k8s_incident":
        reason = "injection" if verdict.label == "injection" else "off_topic"
        audit.log_rejection(endpoint, reason, text, pattern=f"classifier:{verdict.label}")
        raise GuardrailRejection(reason)
    return screened


def screen_notes(text: str | None, endpoint: str = "/diagnose") -> str | None:
    """`notes` are attached to an already-resolved object, so no LLM intent
    classification (spec 013 Design); limits, masking and patterns only."""
    if text is None or not text.strip():
        return None
    return _screen_common(text, endpoint, NOTES_MAX_CHARS).text


def screen_postmortem_field(text: str, endpoint: str = "/diagnose/{job_id}/postmortem") -> str:
    return _screen_common(text, endpoint, POSTMORTEM_MAX_CHARS).text
