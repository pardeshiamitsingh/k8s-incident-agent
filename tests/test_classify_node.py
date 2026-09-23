import pytest

from agent.classify_node import classify_node
from agent.state import AgentState
from collectors.models import IncidentEvidence, ObjectDescribeSnapshot, ObjectRef


def _state_with_evidence() -> AgentState:
    ref = ObjectRef(kind="Pod", namespace="ns", name="p")
    evidence = IncidentEvidence(
        object_ref=ref,
        collected_at="2026-01-01T00:00:00Z",
        events=[],
        describe=ObjectDescribeSnapshot(phase="Running"),
        logs={},
    )
    return AgentState(resolved_object=ref, evidence=evidence)


def test_classify_node_returns_classification():
    result = classify_node(_state_with_evidence())
    assert result == {"classified_failure_classes": ["Unknown"]}


def test_classify_node_requires_evidence():
    ref = ObjectRef(kind="Pod", namespace="ns", name="p")
    with pytest.raises(ValueError):
        classify_node(AgentState(resolved_object=ref))
