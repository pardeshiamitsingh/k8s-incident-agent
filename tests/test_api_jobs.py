from unittest.mock import patch

from agent.models import Diagnosis, RemediationPlan
from agent.state import AgentState
from api.jobs import JobStore
from collectors.models import ObjectRef


def _ref() -> ObjectRef:
    return ObjectRef(kind="Pod", namespace="ns", name="p")


def test_create_job_is_running_with_resolved_object_set():
    store = JobStore()
    job = store.create_job(_ref())

    assert job.status == "running"
    assert job.resolved_object == _ref()
    assert store.get_job(job.job_id) is job


def test_get_job_unknown_id_returns_none():
    store = JobStore()
    assert store.get_job("does-not-exist") is None


@patch("api.jobs.run_agent")
def test_run_job_success_marks_completed_with_result(mock_run_agent):
    store = JobStore()
    job = store.create_job(_ref())

    diagnosis = Diagnosis(
        root_cause="oom", cited_evidence=["e"], cited_runbook_chunks=["c"]
    )
    plan = RemediationPlan(summary="s", steps=["step"])
    mock_run_agent.return_value = AgentState(
        resolved_object=_ref(),
        classified_failure_classes=["OOMKilled"],
        retrieved_chunks=[],
        diagnosis=diagnosis,
        remediation_plan=plan,
    )

    store.run_job(job.job_id, _ref(), notes=None)

    updated = store.get_job(job.job_id)
    assert updated.status == "completed"
    assert updated.classified_failure_classes == ["OOMKilled"]
    assert updated.diagnosis == diagnosis
    assert updated.remediation_plan == plan


@patch("api.jobs.run_agent")
def test_run_job_failure_marks_failed_with_error(mock_run_agent):
    store = JobStore()
    job = store.create_job(_ref())
    mock_run_agent.side_effect = RuntimeError("ollama unreachable")

    store.run_job(job.job_id, _ref(), notes=None)

    updated = store.get_job(job.job_id)
    assert updated.status == "failed"
    assert updated.error == "ollama unreachable"
