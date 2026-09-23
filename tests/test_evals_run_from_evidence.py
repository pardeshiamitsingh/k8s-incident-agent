from unittest.mock import patch

from collectors.models import IncidentEvidence, ObjectDescribeSnapshot, ObjectRef
from evals.run_from_evidence import run_agent_from_evidence


def _evidence() -> IncidentEvidence:
    return IncidentEvidence(
        object_ref=ObjectRef(kind="Pod", namespace="ns", name="p"),
        collected_at="2026-01-01T00:00:00Z",
        events=[],
        describe=ObjectDescribeSnapshot(phase="Running"),
        logs={},
    )


@patch("evals.run_from_evidence.plan_node")
@patch("evals.run_from_evidence.diagnose_node")
@patch("evals.run_from_evidence.retrieve_node")
@patch("evals.run_from_evidence.classify_node")
def test_run_agent_from_evidence_never_calls_collect(
    mock_classify, mock_retrieve, mock_diagnose, mock_plan
):
    mock_classify.return_value = {"classified_failure_classes": ["OOMKilled"]}
    mock_retrieve.return_value = {"retrieved_chunks": []}
    mock_diagnose.return_value = {"diagnosis": None}
    mock_plan.return_value = {"remediation_plan": None}

    evidence = _evidence()
    result = run_agent_from_evidence(evidence, notes="some notes")

    assert result.evidence == evidence
    assert result.notes == "some notes"
    assert result.classified_failure_classes == ["OOMKilled"]
    mock_classify.assert_called_once()
    mock_retrieve.assert_called_once()
    mock_diagnose.assert_called_once()
    mock_plan.assert_called_once()
