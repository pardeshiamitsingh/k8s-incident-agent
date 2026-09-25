"""Data shapes for the input guardrails (spec 013)."""

from typing import Literal

from pydantic import BaseModel, Field


class ScreenedText(BaseModel):
    """Text that passed screening, with PII/secrets already masked and a
    per-type count of what was masked (for audit logging)."""

    text: str
    redactions: dict[str, int] = {}


class IntentVerdict(BaseModel):
    """The intent classifier's whole output. Nothing but a label and a
    short reason is allowed, so a hijacked classifier cannot emit free text."""

    label: Literal["k8s_incident", "off_topic", "injection"]
    reason: str = Field(default="", max_length=200)
