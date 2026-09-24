from unittest.mock import MagicMock, patch

from collectors.models import ObjectRef
from knowledge_base.postmortem import ingest_postmortem, postmortem_chunk_id


def _ref() -> ObjectRef:
    return ObjectRef(kind="Deployment", namespace="ns", name="oom-killed")


@patch("knowledge_base.postmortem.get_vector_store")
def test_ingest_postmortem_writes_one_chunk_per_failure_class(mock_get_vector_store):
    vector_store = MagicMock()
    mock_get_vector_store.return_value = vector_store

    chunk_ids = ingest_postmortem(
        job_id="job-123",
        resolved_object=_ref(),
        failure_classes=["OOMKilled", "CrashLoopBackOff"],
        original_root_cause="memory leak",
        actual_root_cause="undersized limit, not a leak",
        actual_fix="raised memory limit to 256Mi",
    )

    assert chunk_ids == [
        "postmortem-job-123-OOMKilled",
        "postmortem-job-123-CrashLoopBackOff",
    ]
    vector_store.add_documents.assert_called_once()
    documents, kwargs = vector_store.add_documents.call_args
    assert kwargs["ids"] == chunk_ids
    assert len(documents[0]) == 2
    assert documents[0][0].metadata["failure_class"] == "OOMKilled"
    assert documents[0][0].metadata["section"] == "Postmortem"
    assert "undersized limit" in documents[0][0].page_content
    assert "raised memory limit" in documents[0][0].page_content


@patch("knowledge_base.postmortem.get_vector_store")
def test_ingest_postmortem_is_idempotent_by_chunk_id(mock_get_vector_store):
    vector_store = MagicMock()
    mock_get_vector_store.return_value = vector_store

    first = ingest_postmortem(
        job_id="job-123", resolved_object=_ref(), failure_classes=["OOMKilled"],
        original_root_cause="a", actual_root_cause="b", actual_fix="c",
    )
    second = ingest_postmortem(
        job_id="job-123", resolved_object=_ref(), failure_classes=["OOMKilled"],
        original_root_cause="a", actual_root_cause="different now", actual_fix="c",
    )

    assert first == second  # same deterministic id -> upsert, not duplicate


def test_postmortem_chunk_id_deterministic():
    assert postmortem_chunk_id("job-123", "OOMKilled") == "postmortem-job-123-OOMKilled"
