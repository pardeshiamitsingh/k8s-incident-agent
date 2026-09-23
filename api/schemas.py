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
