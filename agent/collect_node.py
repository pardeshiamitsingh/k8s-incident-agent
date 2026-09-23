"""Collect node: wraps spec 001's collect_evidence() (spec 003)."""

import logging

from collectors.collect import collect_evidence

from .state import AgentState

logger = logging.getLogger(__name__)


def collect_node(state: AgentState) -> dict:
    """Fetches evidence for `state.resolved_object` and returns it as the
    `evidence` state update."""
    logger.info(
        "collect: %s %s/%s",
        state.resolved_object.kind, state.resolved_object.namespace,
        state.resolved_object.name,
    )
    evidence = collect_evidence(state.resolved_object)
    return {"evidence": evidence}
