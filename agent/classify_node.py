"""Classify node: deterministic reason-string classification (spec 003)."""

import logging

from .classification import classify_evidence
from .state import AgentState

logger = logging.getLogger(__name__)


def classify_node(state: AgentState) -> dict:
    """Classifies `state.evidence` and returns the result as the
    `classified_failure_classes` state update. Raises if `evidence` hasn't
    been set yet (i.e. `collect_node` hasn't run)."""
    if state.evidence is None:
        raise ValueError("classify_node requires state.evidence to be set")
    failure_classes = classify_evidence(state.evidence)
    logger.info("classify: %s", failure_classes)
    return {"classified_failure_classes": failure_classes}
