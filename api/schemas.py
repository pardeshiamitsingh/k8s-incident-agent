"""API request/response schemas (spec 007).

The request body for POST /diagnose is spec 005's own `IntakeRequest`,
reused directly rather than duplicated here.
"""

from typing import Literal

from pydantic import BaseModel

from agent.models import Diagnosis, RemediationPlan
from collectors.models import ObjectRef
from knowledge_base.models import RunbookChunk


class DiagnoseAccepted(BaseModel):
    job_id: str


class JobStatus(BaseModel):
    """GET /diagnose/{job_id} response. `resolved_object` is always set
    (resolution already succeeded before a job exists); everything else
    stays null until `status == "completed"`."""

    job_id: str
    status: Literal["running", "completed", "failed"]
    resolved_object: ObjectRef
    classified_failure_classes: list[str] | None = None
    retrieved_chunks: list[RunbookChunk] | None = None
    diagnosis: Diagnosis | None = None
    remediation_plan: RemediationPlan | None = None
    error: str | None = None


class PostmortemRequest(BaseModel):
    """POST /diagnose/{job_id}/postmortem body (spec 004)."""

    was_correct: bool
    actual_root_cause: str
    actual_fix: str


class PostmortemAccepted(BaseModel):
    ingested: bool
    """Mirrors `was_correct` -- lets the caller confirm whether this
    submission actually changed what future retrieval returns."""


class QueryRequest(BaseModel):
    """POST /diagnose/query body (spec 008)."""

    query: str


class MentionResult(BaseModel):
    """One detected mention's resolution outcome, within `QueryResponse`."""

    mentioned_service: str
    notes: str | None
    status: Literal["resolved", "ambiguous", "not_found"]
    job_id: str | None = None
    resolved_object: ObjectRef | None = None
    candidates: list[ObjectRef] | None = None


class QueryResponse(BaseModel):
    """POST /diagnose/query response. Always 200 -- a well-formed query
    that resolves none of its mentions is still a complete response, not
    an error."""

    mentions: list[MentionResult]
