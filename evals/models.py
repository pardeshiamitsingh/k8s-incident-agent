"""Data shapes for the evaluation harness (spec 006)."""

from pydantic import BaseModel

from agent.models import Diagnosis, RemediationPlan
from collectors.models import IncidentEvidence


class GoldenCase(BaseModel):
    id: str
    evidence: IncidentEvidence
    expected_failure_classes: list[str]
    root_cause_keywords: list[str]
    remediation_keywords: list[str]
    # Spec 014 retrieval check: runbook file stems that should be retrieved.
    # Empty means "the runbook named like this case's id".
    expected_runbooks: list[str] = []


class CaseResult(BaseModel):
    case_id: str
    classification_correct: bool
    root_cause_keyword_hits: float
    remediation_keyword_hits: float
    llm_judge_score: int | None = None
    llm_judge_rationale: str | None = None
    latency_seconds: float
    diagnosis: Diagnosis
    remediation_plan: RemediationPlan
