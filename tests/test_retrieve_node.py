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


# --- spec 014: evidence-aware queries in hybrid mode -------------------------

from agent.retrieve_node import EVIDENCE_QUERY_MAX_CHARS, retrieve_for_failure_classes  # noqa: E402
from collectors.models import (  # noqa: E402
    IncidentEvidence, K8sEvent, LogsSnapshot, ObjectDescribeSnapshot, ObjectRef,
)


def _evidence_with(log: str, event_message: str = "Back-off restarting failed container") -> IncidentEvidence:
    now = "2026-01-01T00:00:00Z"
    return IncidentEvidence(
        object_ref=ObjectRef(kind="Pod", namespace="ns", name="p"),
        collected_at=now,
        events=[
            K8sEvent(reason="Pulled", type="Normal", count=1, first_seen=now, last_seen=now, message="image pulled"),
            K8sEvent(reason="BackOff", type="Warning", count=3, first_seen=now, last_seen=now, message=event_message),
        ],
        describe=ObjectDescribeSnapshot(phase="Running"),
        logs={"app": LogsSnapshot(current=log)},
    )


@patch("agent.retrieve_node.retrieve_runbooks", return_value=[])
def test_dense_mode_query_is_the_class_name_alone(mock_retrieve, monkeypatch):
    monkeypatch.setenv("INCIDENT_AGENT_RETRIEVAL_MODE", "dense")
    retrieve_for_failure_classes(["CrashLoopBackOff"], _evidence_with("FATAL: password authentication failed"))
    assert mock_retrieve.call_args.args[0] == "CrashLoopBackOff"


@patch("agent.retrieve_node.retrieve_runbooks", return_value=[])
def test_hybrid_query_has_class_log_tail_and_warning_events_but_not_normal_events(mock_retrieve, monkeypatch):
    monkeypatch.setenv("INCIDENT_AGENT_RETRIEVAL_MODE", "hybrid")
    retrieve_for_failure_classes(["CrashLoopBackOff"], _evidence_with("FATAL: password authentication failed"))
    query = mock_retrieve.call_args.args[0]
    assert query.startswith("CrashLoopBackOff: ")
    assert "password authentication failed" in query
    assert "BackOff" in query
    assert "image pulled" not in query


@patch("agent.retrieve_node.retrieve_runbooks", return_value=[])
def test_hybrid_query_is_truncated_but_keeps_the_log_tail_first(mock_retrieve, monkeypatch):
    monkeypatch.setenv("INCIDENT_AGENT_RETRIEVAL_MODE", "hybrid")
    retrieve_for_failure_classes(
        ["OOMKilled"], _evidence_with("LOGMARKER", event_message="x" * 2000)
    )
    query = mock_retrieve.call_args.args[0]
    assert len(query) <= EVIDENCE_QUERY_MAX_CHARS
    assert "LOGMARKER" in query
