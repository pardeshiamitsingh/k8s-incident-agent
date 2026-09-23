import os

os.environ.setdefault("INCIDENT_AGENT_API_TOKEN", "test-token")

from unittest.mock import MagicMock, patch  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from agent.models import Diagnosis, RemediationPlan  # noqa: E402
from api.app import app  # noqa: E402
from api.jobs import Job  # noqa: E402
from collectors.models import ObjectRef  # noqa: E402
from intake.models import ResolutionError  # noqa: E402

client = TestClient(app)
AUTH_HEADERS = {"Authorization": "Bearer test-token"}


def test_healthz_no_auth_required():
    response = client.get("/healthz")
    assert response.status_code == 200


def test_diagnose_without_token_is_401():
    response = client.post("/diagnose", json={"namespace": "ns", "name": "x"})
    assert response.status_code == 401


def test_diagnose_missing_required_field_is_422():
    response = client.post(
        "/diagnose", json={"namespace": "ns"}, headers=AUTH_HEADERS
    )
    assert response.status_code == 422


@patch("api.app.resolve_intake")
def test_diagnose_not_found_is_404(mock_resolve):
    mock_resolve.return_value = ResolutionError(reason="not_found", message="nope")

    response = client.post(
        "/diagnose", json={"namespace": "ns", "name": "x"}, headers=AUTH_HEADERS
    )

    assert response.status_code == 404


@patch("api.app.resolve_intake")
def test_diagnose_ambiguous_is_409(mock_resolve):
    mock_resolve.return_value = ResolutionError(reason="ambiguous", message="pick one")

    response = client.post(
        "/diagnose", json={"namespace": "ns", "name": "w"}, headers=AUTH_HEADERS
    )

    assert response.status_code == 409


@patch("api.app.job_store")
@patch("api.app.resolve_intake")
def test_diagnose_success_returns_202_and_job_id(mock_resolve, mock_job_store):
    mock_resolve.return_value = ObjectRef(kind="Pod", namespace="ns", name="x")
    job = MagicMock(job_id="job-123")
    mock_job_store.create_job.return_value = job

    response = client.post(
        "/diagnose", json={"namespace": "ns", "name": "x"}, headers=AUTH_HEADERS
    )

    assert response.status_code == 202
    assert response.json() == {"job_id": "job-123"}
    mock_job_store.create_job.assert_called_once()


def test_get_diagnosis_unknown_job_is_404():
    response = client.get("/diagnose/does-not-exist", headers=AUTH_HEADERS)
    assert response.status_code == 404


@patch("api.app.job_store")
def test_get_diagnosis_returns_job_status(mock_job_store):
    job = Job(
        job_id="job-123",
        status="completed",
        resolved_object=ObjectRef(kind="Pod", namespace="ns", name="x"),
        classified_failure_classes=["OOMKilled"],
        retrieved_chunks=[],
        diagnosis=Diagnosis(
            root_cause="oom", cited_evidence=["e"], cited_runbook_chunks=["c"]
        ),
        remediation_plan=RemediationPlan(summary="s", steps=["step"]),
    )
    mock_job_store.get_job.return_value = job

    response = client.get("/diagnose/job-123", headers=AUTH_HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["diagnosis"]["root_cause"] == "oom"
