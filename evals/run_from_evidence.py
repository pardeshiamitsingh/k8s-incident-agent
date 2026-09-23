"""Runs the agent's reasoning nodes against frozen evidence (spec 006).

Skips spec 003's `collect` node entirely -- eval runs must be fast and
not depend on a live cluster. The four node functions are already plain,
independently-callable functions, so this is just the same sequence
`agent.graph`'s compiled `StateGraph` encodes, entered one node later; no
new graph definition needed.
"""

from agent.classify_node import classify_node
from agent.diagnose_node import diagnose_node
from agent.plan_node import plan_node
from agent.retrieve_node import retrieve_node
from agent.state import AgentState
from collectors.models import IncidentEvidence


def run_agent_from_evidence(
    evidence: IncidentEvidence, notes: str | None = None
) -> AgentState:
    state = AgentState(resolved_object=evidence.object_ref, notes=notes, evidence=evidence)

    state = state.model_copy(update=classify_node(state))
    state = state.model_copy(update=retrieve_node(state))
    state = state.model_copy(update=diagnose_node(state))
    state = state.model_copy(update=plan_node(state))

    return state
