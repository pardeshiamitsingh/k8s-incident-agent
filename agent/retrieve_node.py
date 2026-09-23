"""Retrieve node: wraps spec 002's retrieve_runbooks() (spec 003).

Multi-failure-class evidence retrieves separately per class (k=3 each)
and merges, deduped by chunk ID, rather than joining classes into one
query string -- keeps each class's query semantically clean.

Unknown evidence (no reason string matched anything in the classifier's
table) falls back to a query built from the evidence's own raw reason/
message text, so retrieval still has something to work with instead of
querying the literal string "Unknown".
"""

import logging

from collectors.models import IncidentEvidence
from knowledge_base.models import RunbookChunk
from knowledge_base.retrieve import retrieve_runbooks

from .classification import UNKNOWN
from .state import AgentState

logger = logging.getLogger(__name__)

CHUNKS_PER_FAILURE_CLASS = 3
UNKNOWN_QUERY_CHUNKS = 5


def retrieve_node(state: AgentState) -> dict:
    """Retrieves runbook chunks for `state.classified_failure_classes` (or
    a raw-text fallback query if classification came back `Unknown`) and
    returns them as the `retrieved_chunks` state update."""
    if state.evidence is None:
        raise ValueError("retrieve_node requires state.evidence to be set")

    if state.classified_failure_classes == [UNKNOWN]:
        query = _raw_text_query(state.evidence)
        logger.info("retrieve: Unknown evidence, raw-text query=%r", query)
        chunks = retrieve_runbooks(query, k=UNKNOWN_QUERY_CHUNKS)
    else:
        chunks = _retrieve_per_failure_class(state.classified_failure_classes)

    logger.info("retrieve: %d chunk(s): %s", len(chunks), [c.id for c in chunks])
    return {"retrieved_chunks": chunks}


def _retrieve_per_failure_class(failure_classes: list[str]) -> list[RunbookChunk]:
    """Queries `retrieve_runbooks` once per failure class and merges the
    results, keeping first-seen order and dropping later duplicate chunk
    IDs."""
    chunks: list[RunbookChunk] = []
    seen_ids: set[str] = set()
    for failure_class in failure_classes:
        for chunk in retrieve_runbooks(failure_class, k=CHUNKS_PER_FAILURE_CLASS):
            if chunk.id not in seen_ids:
                seen_ids.add(chunk.id)
                chunks.append(chunk)
    return chunks


def _raw_text_query(evidence: IncidentEvidence) -> str:
    """Builds a free-text retrieval query from evidence's own reason/
    message strings (recursing into owned pods), for the case where the
    classifier matched nothing. Falls back to a generic phrase if there's
    no text at all to work with."""
    parts: list[str] = []
    for container_status in evidence.describe.container_statuses:
        if container_status.state.reason:
            parts.append(container_status.state.reason)
        if container_status.state.message:
            parts.append(container_status.state.message)
    for event in evidence.events:
        parts.append(event.reason)
        parts.append(event.message)
    for pod_evidence in evidence.pods:
        pod_text = _raw_text_query(pod_evidence)
        if pod_text:
            parts.append(pod_text)
    return " ".join(part for part in parts if part) or "unknown kubernetes failure"
