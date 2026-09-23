"""Builds and runs the Phase 3 agent graph (spec 003).

collect -> classify -> retrieve -> diagnose -> plan -> END, linear, no
conditional branches in v1. Spec 005's intake node, once implemented,
slots in ahead of `collect` -- the state fields it needs
(`resolved_object`, `notes`) already exist here unchanged.
"""

import logging

from langgraph.graph import END, StateGraph

from collectors.models import ObjectRef

from .classify_node import classify_node
from .collect_node import collect_node
from .diagnose_node import diagnose_node
from .plan_node import plan_node
from .retrieve_node import retrieve_node
from .state import AgentState

logger = logging.getLogger(__name__)


def build_graph():
    """Builds and compiles the collect->classify->retrieve->diagnose->plan
    graph. A fresh compiled graph per call keeps this function cheap and
    stateless; nothing here is expensive enough to warrant caching it."""
    graph = StateGraph(AgentState)
    graph.add_node("collect", collect_node)
    graph.add_node("classify", classify_node)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("diagnose", diagnose_node)
    graph.add_node("plan", plan_node)

    graph.set_entry_point("collect")
    graph.add_edge("collect", "classify")
    graph.add_edge("classify", "retrieve")
    graph.add_edge("retrieve", "diagnose")
    graph.add_edge("diagnose", "plan")
    graph.add_edge("plan", END)

    return graph.compile()


def run_agent(object_ref: ObjectRef, notes: str | None = None) -> AgentState:
    """Runs the full agent graph for `object_ref` end to end and returns
    the final `AgentState` (evidence, classification, retrieved chunks,
    diagnosis, and remediation plan all populated). The module's single
    public entrypoint -- mirrors `collect_evidence` and `retrieve_runbooks`
    as "the one thing later code imports"."""
    logger.info(
        "running agent for %s %s/%s",
        object_ref.kind, object_ref.namespace, object_ref.name,
    )
    compiled_graph = build_graph()
    result = compiled_graph.invoke(AgentState(resolved_object=object_ref, notes=notes))
    return AgentState.model_validate(result)
