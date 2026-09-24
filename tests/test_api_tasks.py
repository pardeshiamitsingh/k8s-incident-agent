from unittest.mock import MagicMock, patch

from agent.models import Diagnosis, RemediationPlan
from agent.state import AgentState
from api.jobs import Job
from api.tasks import run_diagnosis_job
from collectors.models import ObjectRef


def _ref() -> ObjectRef:
    return ObjectRef(kind="Pod", namespace="ns", name="p")


@patch("api.tasks.RedisJobStore")
@patch("api.tasks.get_redis_connection")
@patch("api.tasks.run_agent")
def test_run_diagnosis_job_success_marks_completed(
    mock_run_agent, mock_get_connection, mock_job_store_cls
):
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

    store = MagicMock()
    store.get_job.return_value = Job(job_id="job-1", status="running", resolved_object=_ref())
    mock_job_store_cls.return_value = store

    run_diagnosis_job("job-1", _ref(), notes=None)

    saved_job = store.save.call_args.args[0]
    assert saved_job.status == "completed"
    assert saved_job.classified_failure_classes == ["OOMKilled"]
    assert saved_job.diagnosis == diagnosis
    assert saved_job.remediation_plan == plan


@patch("api.tasks.RedisJobStore")
@patch("api.tasks.get_redis_connection")
@patch("api.tasks.run_agent")
def test_run_diagnosis_job_failure_marks_failed(
    mock_run_agent, mock_get_connection, mock_job_store_cls
):
    mock_run_agent.side_effect = RuntimeError("ollama unreachable")

    store = MagicMock()
    store.get_job.return_value = Job(job_id="job-1", status="running", resolved_object=_ref())
    mock_job_store_cls.return_value = store

    run_diagnosis_job("job-1", _ref(), notes=None)

    saved_job = store.save.call_args.args[0]
    assert saved_job.status == "failed"
    assert saved_job.error == "ollama unreachable"


@patch("api.tasks.RedisJobStore")
@patch("api.tasks.get_redis_connection")
@patch("api.tasks.run_agent")
def test_run_diagnosis_job_missing_job_record_does_not_raise(
    mock_run_agent, mock_get_connection, mock_job_store_cls
):
    # Defensive: if the job's TTL somehow expired before the worker got to
    # it, there's nothing to update -- shouldn't crash the worker.
    mock_run_agent.side_effect = RuntimeError("boom")
    store = MagicMock()
    store.get_job.return_value = None
    mock_job_store_cls.return_value = store

    run_diagnosis_job("job-1", _ref(), notes=None)  # no exception

    store.save.assert_not_called()
