from unittest.mock import patch

from agent.retrieve_node import retrieve_node
from agent.state import AgentState
from collectors.models import (
    ContainerState,
    ContainerStatus,
    IncidentEvidence,
    ObjectDescribeSnapshot,
    ObjectRef,
)
from knowledge_base.models import RunbookChunk


def _chunk(chunk_id: str, failure_class: str) -> RunbookChunk:
    return RunbookChunk(
        id=chunk_id, failure_class=failure_class, section="Diagnosis",
        text="text", source_file=f"{failure_class}.md",
    )


def _state(classified, container_reason=None) -> AgentState:
    ref = ObjectRef(kind="Pod", namespace="ns", name="p")
    container_statuses = []
    if container_reason:
        container_statuses.append(
            ContainerStatus(
                name="app",
                state=ContainerState(phase="waiting", reason=container_reason),
                restart_count=0,
                image="x",
            )
        )
    evidence = IncidentEvidence(
        object_ref=ref,
        collected_at="2026-01-01T00:00:00Z",
        events=[],
        describe=ObjectDescribeSnapshot(
            phase="Running", container_statuses=container_statuses
        ),
        logs={},
    )
    return AgentState(
        resolved_object=ref, evidence=evidence, classified_failure_classes=classified
    )


@patch("agent.retrieve_node.retrieve_runbooks")
def test_retrieve_node_queries_per_failure_class_and_dedupes(mock_retrieve):
    mock_retrieve.side_effect = lambda query, k: {
        "OOMKilled": [_chunk("oom-killed#diagnosis", "OOMKilled")],
        "Pending": [
            _chunk("pending-unschedulable#diagnosis", "Pending"),
            _chunk("oom-killed#diagnosis", "OOMKilled"),  # duplicate id
        ],
    }[query]

    result = retrieve_node(_state(["OOMKilled", "Pending"]))

    ids = [c.id for c in result["retrieved_chunks"]]
    assert ids == ["oom-killed#diagnosis", "pending-unschedulable#diagnosis"]
    assert mock_retrieve.call_count == 2


@patch("agent.retrieve_node.retrieve_runbooks")
def test_retrieve_node_unknown_falls_back_to_raw_text_query(mock_retrieve):
    mock_retrieve.return_value = [_chunk("some#chunk", "Something")]

    result = retrieve_node(
        _state(["Unknown"], container_reason="SomeWeirdReason")
    )

    query_used = mock_retrieve.call_args.args[0]
    assert "SomeWeirdReason" in query_used
    assert result["retrieved_chunks"] == [_chunk("some#chunk", "Something")]
