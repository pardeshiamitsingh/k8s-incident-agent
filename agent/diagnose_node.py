"""Diagnose node: structured, cited root-cause diagnosis (spec 003)."""

import logging

from .formatting import format_chunks, format_evidence
from .llm import get_llm
from .models import Diagnosis
from .state import AgentState

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a Kubernetes incident diagnosis assistant. You are given structured
evidence collected from a live cluster and relevant runbook excerpts.

Produce a root cause diagnosis. You MUST cite:
- cited_evidence: the specific evidence lines (e.g. "Container app: \
state=terminated reason=OOMKilled") that support your diagnosis, quoted or \
closely paraphrased from the evidence given.
- cited_runbook_chunks: the runbook chunk IDs (the bracketed [id] shown \
before each excerpt, e.g. "oom-killed#diagnosis") that informed your \
diagnosis.

Do not invent evidence or chunk IDs that were not given to you. If the \
evidence is ambiguous or incomplete, say so in root_cause rather than \
guessing with false confidence.
"""


def diagnose_node(state: AgentState) -> dict:
    """Calls the local LLM with structured output to produce a cited
    `Diagnosis` from `state.evidence` and `state.retrieved_chunks`, and
    returns it as the `diagnosis` state update."""
    if state.evidence is None:
        raise ValueError("diagnose_node requires state.evidence to be set")

    evidence_text = format_evidence(state.evidence)
    chunks_text = format_chunks(state.retrieved_chunks)
    notes_text = f"\nUser-provided notes: {state.notes}" if state.notes else ""

    user_prompt = (
        f"Evidence:\n{evidence_text}\n{notes_text}\n\n"
        f"Relevant runbook excerpts:\n{chunks_text}\n\n"
        "Diagnose the root cause."
    )

    logger.info(
        "diagnose: %s %s/%s, %d retrieved chunk(s)",
        state.resolved_object.kind, state.resolved_object.namespace,
        state.resolved_object.name, len(state.retrieved_chunks),
    )
    structured_llm = get_llm().with_structured_output(Diagnosis)
    diagnosis = structured_llm.invoke(
        [("system", SYSTEM_PROMPT), ("user", user_prompt)]
    )
    logger.info("diagnose: root_cause=%r", diagnosis.root_cause)
    return {"diagnosis": diagnosis}
