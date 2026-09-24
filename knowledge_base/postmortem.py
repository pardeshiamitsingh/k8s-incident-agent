"""Postmortem write-back into the existing runbook collection (spec 004).

A postmortem is just another document in the same Chroma collection the
12 hand-authored runbooks live in, tagged so it's retrievable by the same
failure-class query `agent.retrieve_node` already makes. No changes
needed there -- this module only adds to what it already queries.
"""

import logging

from langchain_core.documents import Document

from collectors.models import ObjectRef

from .ingest import get_vector_store

logger = logging.getLogger(__name__)


def postmortem_chunk_id(job_id: str, failure_class: str) -> str:
    return f"postmortem-{job_id}-{failure_class}"


def _postmortem_text(
    resolved_object: ObjectRef,
    original_root_cause: str,
    actual_root_cause: str,
    actual_fix: str,
) -> str:
    return (
        f"Incident: {resolved_object.kind} {resolved_object.namespace}/"
        f"{resolved_object.name}\n"
        f"Original diagnosis: {original_root_cause}\n"
        f"Actual root cause: {actual_root_cause}\n"
        f"Actual fix applied: {actual_fix}"
    )


def ingest_postmortem(
    job_id: str,
    resolved_object: ObjectRef,
    failure_classes: list[str],
    original_root_cause: str,
    actual_root_cause: str,
    actual_fix: str,
) -> list[str]:
    """Upserts one chunk per failure class (mirroring retrieve_node's own
    per-class handling for multi-failure-class Deployments), so the
    postmortem is retrievable regardless of which class a future incident
    matches. Idempotent: resubmitting for the same job_id/failure_class
    replaces the existing chunk rather than duplicating it. Returns the
    chunk IDs written."""
    text = _postmortem_text(
        resolved_object, original_root_cause, actual_root_cause, actual_fix
    )
    vector_store = get_vector_store()

    chunk_ids = [postmortem_chunk_id(job_id, fc) for fc in failure_classes]
    documents = [
        Document(
            page_content=text,
            metadata={
                "failure_class": failure_class,
                "section": "Postmortem",
                "source_file": chunk_id,
            },
        )
        for chunk_id, failure_class in zip(chunk_ids, failure_classes)
    ]
    vector_store.add_documents(documents, ids=chunk_ids)

    logger.info(
        "ingested postmortem for job %s: %d chunk(s) across failure_classes=%s",
        job_id, len(chunk_ids), failure_classes,
    )
    return chunk_ids
