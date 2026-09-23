from unittest.mock import MagicMock, patch

import pytest

from agent.diagnose_node import diagnose_node
from agent.models import Diagnosis
from agent.state import AgentState
from collectors.models import IncidentEvidence, ObjectDescribeSnapshot, ObjectRef


def _state() -> AgentState:
    ref = ObjectRef(kind="Pod", namespace="ns", name="p")
    evidence = IncidentEvidence(
        object_ref=ref,
        collected_at="2026-01-01T00:00:00Z",
        events=[],
        describe=ObjectDescribeSnapshot(phase="Running"),
        logs={},
    )
    return AgentState(resolved_object=ref, evidence=evidence)


@patch("agent.diagnose_node.get_llm")
def test_diagnose_node_returns_structured_diagnosis(mock_get_llm):
    expected = Diagnosis(
        root_cause="oom",
        cited_evidence=["evidence line"],
        cited_runbook_chunks=["oom-killed#diagnosis"],
    )
    structured_llm = MagicMock()
    structured_llm.invoke.return_value = expected
    llm = MagicMock()
    llm.with_structured_output.return_value = structured_llm
    mock_get_llm.return_value = llm

    result = diagnose_node(_state())

    llm.with_structured_output.assert_called_once_with(Diagnosis)
    assert result == {"diagnosis": expected}


def test_diagnose_node_requires_evidence():
    ref = ObjectRef(kind="Pod", namespace="ns", name="p")
    with pytest.raises(ValueError):
        diagnose_node(AgentState(resolved_object=ref))


@patch("agent.diagnose_node.get_llm")
def test_diagnose_node_strips_brackets_from_chunk_ids(mock_get_llm):
    # Observed in practice: the LLM sometimes copies the "[id]" display
    # formatting from the prompt verbatim instead of the bare ID.
    llm_output = Diagnosis(
        root_cause="oom",
        cited_evidence=["evidence line"],
        cited_runbook_chunks=["[oom-killed#diagnosis]", "oom-killed#remediation"],
    )
    structured_llm = MagicMock()
    structured_llm.invoke.return_value = llm_output
    llm = MagicMock()
    llm.with_structured_output.return_value = structured_llm
    mock_get_llm.return_value = llm

    result = diagnose_node(_state())

    assert result["diagnosis"].cited_runbook_chunks == [
        "oom-killed#diagnosis",
        "oom-killed#remediation",
    ]
