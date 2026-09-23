from unittest.mock import MagicMock, patch

import pytest

from agent.models import Diagnosis, RemediationPlan
from agent.plan_node import plan_node
from agent.state import AgentState
from collectors.models import IncidentEvidence, ObjectDescribeSnapshot, ObjectRef


def _state(with_diagnosis=True) -> AgentState:
    ref = ObjectRef(kind="Pod", namespace="ns", name="p")
    evidence = IncidentEvidence(
        object_ref=ref,
        collected_at="2026-01-01T00:00:00Z",
        events=[],
        describe=ObjectDescribeSnapshot(phase="Running"),
        logs={},
    )
    diagnosis = None
    if with_diagnosis:
        diagnosis = Diagnosis(
            root_cause="oom",
            cited_evidence=["evidence line"],
            cited_runbook_chunks=["oom-killed#diagnosis"],
        )
    return AgentState(resolved_object=ref, evidence=evidence, diagnosis=diagnosis)


@patch("agent.plan_node.get_llm")
def test_plan_node_returns_structured_plan(mock_get_llm):
    expected = RemediationPlan(summary="raise limit", steps=["do x"], caveats=None)
    structured_llm = MagicMock()
    structured_llm.invoke.return_value = expected
    llm = MagicMock()
    llm.with_structured_output.return_value = structured_llm
    mock_get_llm.return_value = llm

    result = plan_node(_state())

    llm.with_structured_output.assert_called_once_with(RemediationPlan)
    assert result == {"remediation_plan": expected}


def test_plan_node_requires_diagnosis():
    with pytest.raises(ValueError):
        plan_node(_state(with_diagnosis=False))
