from unittest.mock import MagicMock

from agent.models import Diagnosis, RemediationPlan
from api.jobs import KEY_PREFIX, Job, RedisJobStore
from collectors.models import ObjectRef


def _ref() -> ObjectRef:
    return ObjectRef(kind="Pod", namespace="ns", name="p")


def test_create_job_is_running_with_resolved_object_set():
    redis_mock = MagicMock()
    store = RedisJobStore(redis_mock, ttl_seconds=100)

    job = store.create_job(_ref())

    assert job.status == "running"
    assert job.resolved_object == _ref()
    redis_mock.set.assert_called_once_with(
        KEY_PREFIX + job.job_id, job.model_dump_json(), ex=100
    )


def test_get_job_unknown_id_returns_none():
    redis_mock = MagicMock()
    redis_mock.get.return_value = None
    store = RedisJobStore(redis_mock)

    assert store.get_job("does-not-exist") is None


def test_get_job_round_trips_via_json():
    redis_mock = MagicMock()
    store = RedisJobStore(redis_mock)
    job = Job(
        job_id="abc",
        status="completed",
        resolved_object=_ref(),
        classified_failure_classes=["OOMKilled"],
        retrieved_chunks=[],
        diagnosis=Diagnosis(
            root_cause="oom", cited_evidence=["e"], cited_runbook_chunks=["c"]
        ),
        remediation_plan=RemediationPlan(summary="s", steps=["step"]),
    )
    redis_mock.get.return_value = job.model_dump_json()

    result = store.get_job("abc")

    assert result == job
    redis_mock.get.assert_called_once_with(KEY_PREFIX + "abc")


def test_save_writes_with_configured_ttl():
    redis_mock = MagicMock()
    store = RedisJobStore(redis_mock, ttl_seconds=42)
    job = Job(job_id="abc", status="running", resolved_object=_ref())

    store.save(job)

    redis_mock.set.assert_called_once_with(
        KEY_PREFIX + "abc", job.model_dump_json(), ex=42
    )
