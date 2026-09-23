"""Structured LLM outputs for the Diagnose and Plan nodes (spec 003).

Citations are required, non-empty fields, not just a prompt instruction --
constitution principle 4 ("every diagnosis is explainable") is enforced by
schema validation, so an uncited diagnosis is a hard failure, not a
silently-accepted soft one.
"""

from pydantic import BaseModel, Field


class Diagnosis(BaseModel):
    """The Diagnose node's structured output."""

    root_cause: str
    """Plain-language root cause."""
    cited_evidence: list[str] = Field(min_length=1)
    """Evidence lines that support the root cause; must be non-empty."""
    cited_runbook_chunks: list[str] = Field(min_length=1)
    """IDs of retrieved runbook chunks that informed the diagnosis; must be
    non-empty."""


class RemediationPlan(BaseModel):
    """The Plan node's structured output -- a proposal for a human to
    review and carry out, never executed by the agent itself."""

    summary: str
    """One or two sentences on what to do and why."""
    steps: list[str] = Field(min_length=1)
    """Concrete, ordered, actionable steps."""
    caveats: str | None = None
    """Anything the operator should double-check before acting, or None."""
