from unittest.mock import MagicMock, patch

from agent.models import Diagnosis, RemediationPlan
from agent.state import AgentState
from collectors.models import ObjectRef
from evals.judge import JudgeVerdict, judge_case
from evals.models import GoldenCase


@patch("evals.judge.get_llm")
def test_judge_case_returns_structured_verdict(mock_get_llm):
    expected = JudgeVerdict(score=4, rationale="mostly on target")
    structured_llm = MagicMock()
    structured_llm.invoke.return_value = expected
    llm = MagicMock()
    llm.with_structured_output.return_value = structured_llm
    mock_get_llm.return_value = llm

    case = GoldenCase.model_construct(
        id="c1", evidence=None, expected_failure_classes=["OOMKilled"],
        root_cause_keywords=["memory"], remediation_keywords=["limit"],
    )
    state = AgentState(
        resolved_object=ObjectRef(kind="Pod", namespace="ns", name="p"),
        diagnosis=Diagnosis(root_cause="oom", cited_evidence=["e"], cited_runbook_chunks=["c"]),
        remediation_plan=RemediationPlan(summary="s", steps=["raise limit"]),
    )

    verdict = judge_case(case, state)

    llm.with_structured_output.assert_called_once_with(JudgeVerdict)
    assert verdict == expected
