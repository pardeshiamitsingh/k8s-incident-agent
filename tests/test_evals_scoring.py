from agent.models import Diagnosis, RemediationPlan
from agent.state import AgentState
from collectors.models import ObjectRef
from evals.models import GoldenCase
from evals.scoring import (
    classification_correct,
    keyword_hit_rate,
    remediation_keyword_hits,
    root_cause_keyword_hits,
)


def _case(**overrides) -> GoldenCase:
    defaults = dict(
        id="c1",
        evidence=None,
        expected_failure_classes=["OOMKilled"],
        root_cause_keywords=["memory", "oom"],
        remediation_keywords=["limit"],
    )
    defaults.update(overrides)
    return GoldenCase.model_construct(**defaults)


def _state(root_cause="", steps=None, classified=None) -> AgentState:
    ref = ObjectRef(kind="Pod", namespace="ns", name="p")
    return AgentState(
        resolved_object=ref,
        classified_failure_classes=classified or [],
        diagnosis=Diagnosis(
            root_cause=root_cause, cited_evidence=["e"], cited_runbook_chunks=["c"]
        ),
        remediation_plan=RemediationPlan(summary="s", steps=steps or ["step"]),
    )


def test_keyword_hit_rate_full_match():
    assert keyword_hit_rate("the OOM killer struck", ["OOM", "killer"]) == 1.0


def test_keyword_hit_rate_partial_match():
    assert keyword_hit_rate("the OOM killer struck", ["OOM", "leak"]) == 0.5


def test_keyword_hit_rate_case_insensitive():
    assert keyword_hit_rate("Memory Limit Exceeded", ["memory", "LIMIT"]) == 1.0


def test_keyword_hit_rate_empty_keywords_is_full_credit():
    assert keyword_hit_rate("anything", []) == 1.0


def test_classification_correct_exact_match():
    case = _case(expected_failure_classes=["OOMKilled"])
    state = _state(classified=["OOMKilled"])
    assert classification_correct(case, state) is True


def test_classification_correct_set_match_ignores_order():
    case = _case(expected_failure_classes=["A", "B"])
    state = _state(classified=["B", "A"])
    assert classification_correct(case, state) is True


def test_classification_correct_mismatch():
    case = _case(expected_failure_classes=["OOMKilled"])
    state = _state(classified=["CrashLoopBackOff"])
    assert classification_correct(case, state) is False


def test_root_cause_keyword_hits():
    case = _case(root_cause_keywords=["memory", "oom"])
    state = _state(root_cause="container ran out of memory")
    assert root_cause_keyword_hits(case, state) == 0.5


def test_remediation_keyword_hits():
    case = _case(remediation_keywords=["limit", "request"])
    state = _state(steps=["raise the memory limit", "update the request too"])
    assert remediation_keyword_hits(case, state) == 1.0
