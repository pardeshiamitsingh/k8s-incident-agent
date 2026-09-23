from unittest.mock import patch

from agent.collect_node import collect_node
from agent.state import AgentState
from collectors.models import IncidentEvidence, ObjectDescribeSnapshot, ObjectRef


@patch("agent.collect_node.collect_evidence")
def test_collect_node_sets_evidence(mock_collect_evidence):
    ref = ObjectRef(kind="Pod", namespace="ns", name="p")
    evidence = IncidentEvidence(
        object_ref=ref,
        collected_at="2026-01-01T00:00:00Z",
        events=[],
        describe=ObjectDescribeSnapshot(phase="Running"),
        logs={},
    )
    mock_collect_evidence.return_value = evidence

    result = collect_node(AgentState(resolved_object=ref))

    mock_collect_evidence.assert_called_once_with(ref)
    assert result == {"evidence": evidence}
