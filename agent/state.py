"""Shared LangGraph state for the Phase 3 agent graph (spec 003).

Field names for `resolved_object` and `notes` match spec 005's
already-defined state fields exactly, so Phase 5's intake node can later
be inserted ahead of `collect` without renaming anything downstream.
"""

from pydantic import BaseModel

from collectors.models import IncidentEvidence, ObjectRef
from knowledge_base.models import RunbookChunk

from .models import Diagnosis, RemediationPlan


class AgentState(BaseModel):
    """State threaded through every node of the collect->classify->retrieve
    ->diagnose->plan graph. Each node reads the fields it needs and returns
    a partial dict of the fields it sets; LangGraph merges those into this
    state between node runs."""

    resolved_object: ObjectRef
    """The object to investigate. Set by the caller (or, once spec 005 is
    implemented, by an intake node ahead of `collect`)."""
    notes: str | None = None
    """Free-text context passed through unparsed to the Diagnose node."""

    evidence: IncidentEvidence | None = None
    """Set by `collect_node`."""
    classified_failure_classes: list[str] = []
    """Set by `classify_node`. `["Unknown"]` if no known reason matched."""
    retrieved_chunks: list[RunbookChunk] = []
    """Set by `retrieve_node`."""
    diagnosis: Diagnosis | None = None
    """Set by `diagnose_node`."""
    remediation_plan: RemediationPlan | None = None
    """Set by `plan_node`, the graph's final output."""
