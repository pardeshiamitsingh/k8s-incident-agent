import os

os.environ.setdefault("INCIDENT_AGENT_API_TOKEN", "test-token")

from unittest.mock import MagicMock, patch  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from agent.models import Diagnosis, RemediationPlan  # noqa: E402
from api.app import app  # noqa: E402
from api.jobs import Job  # noqa: E402
from collectors.models import ObjectRef  # noqa: E402
from intake.models import ResolutionError  # noqa: E402
from nlintake.models import AmbiguousMatch, DetectedMention, NotFound  # noqa: E402

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


@patch("api.app.queue")
@patch("api.app.job_store")
@patch("api.app.resolve_intake")
def test_diagnose_success_returns_202_and_job_id(mock_resolve, mock_job_store, mock_queue):
    mock_resolve.return_value = ObjectRef(kind="Pod", namespace="ns", name="x")
    job = MagicMock(job_id="job-123")
    mock_job_store.create_job.return_value = job
    mock_queue.count = 0

    response = client.post(
        "/diagnose", json={"namespace": "ns", "name": "x"}, headers=AUTH_HEADERS
    )

    assert response.status_code == 202
    assert response.json() == {"job_id": "job-123"}
    mock_job_store.create_job.assert_called_once()
    mock_queue.enqueue.assert_called_once()


@patch("api.app.queue")
@patch("api.app.job_store")
@patch("api.app.resolve_intake")
def test_diagnose_backpressure_returns_429_when_queue_full(
    mock_resolve, mock_job_store, mock_queue
):
    mock_resolve.return_value = ObjectRef(kind="Pod", namespace="ns", name="x")
    mock_queue.count = 999  # well past MAX_IN_FLIGHT_JOBS

    response = client.post(
        "/diagnose", json={"namespace": "ns", "name": "x"}, headers=AUTH_HEADERS
    )

    assert response.status_code == 429
    mock_job_store.create_job.assert_not_called()
    mock_queue.enqueue.assert_not_called()


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


def _completed_job() -> Job:
    return Job(
        job_id="job-123",
        status="completed",
        resolved_object=ObjectRef(kind="Deployment", namespace="ns", name="x"),
        classified_failure_classes=["OOMKilled"],
        retrieved_chunks=[],
        diagnosis=Diagnosis(
            root_cause="oom", cited_evidence=["e"], cited_runbook_chunks=["c"]
        ),
        remediation_plan=RemediationPlan(summary="s", steps=["step"]),
    )


def test_postmortem_unknown_job_is_404():
    response = client.post(
        "/diagnose/does-not-exist/postmortem",
        json={"was_correct": True, "actual_root_cause": "x", "actual_fix": "y"},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 404


@patch("api.app.job_store")
def test_postmortem_running_job_is_409(mock_job_store):
    job = _completed_job()
    job.status = "running"
    mock_job_store.get_job.return_value = job

    response = client.post(
        "/diagnose/job-123/postmortem",
        json={"was_correct": True, "actual_root_cause": "x", "actual_fix": "y"},
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 409


@patch("api.app.ingest_postmortem")
@patch("api.app.job_store")
def test_postmortem_correct_ingests_and_returns_ingested_true(
    mock_job_store, mock_ingest
):
    mock_job_store.get_job.return_value = _completed_job()

    response = client.post(
        "/diagnose/job-123/postmortem",
        json={
            "was_correct": True,
            "actual_root_cause": "undersized limit",
            "actual_fix": "raised memory limit",
        },
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 200
    assert response.json() == {"ingested": True}
    mock_ingest.assert_called_once_with(
        job_id="job-123",
        resolved_object=ObjectRef(kind="Deployment", namespace="ns", name="x"),
        failure_classes=["OOMKilled"],
        original_root_cause="oom",
        actual_root_cause="undersized limit",
        actual_fix="raised memory limit",
    )


@patch("api.app.ingest_postmortem")
@patch("api.app.job_store")
def test_postmortem_incorrect_does_not_ingest(mock_job_store, mock_ingest):
    mock_job_store.get_job.return_value = _completed_job()

    response = client.post(
        "/diagnose/job-123/postmortem",
        json={"was_correct": False, "actual_root_cause": "x", "actual_fix": "y"},
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 200
    assert response.json() == {"ingested": False}
    mock_ingest.assert_not_called()


@patch("api.app.queue")
@patch("api.app.job_store")
@patch("api.app.resolve_mention")
@patch("api.app.decompose_query")
def test_diagnose_query_single_mention_resolves(
    mock_decompose, mock_resolve_mention, mock_job_store, mock_queue
):
    mock_decompose.return_value = [
        DetectedMention(mentioned_service="payment", notes="down")
    ]
    mock_resolve_mention.return_value = ObjectRef(
        kind="Deployment", namespace="ns", name="payment-service"
    )
    job = MagicMock(job_id="job-abc")
    mock_job_store.create_job.return_value = job
    mock_queue.count = 0

    response = client.post(
        "/diagnose/query", json={"query": "payment is down"}, headers=AUTH_HEADERS
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["mentions"]) == 1
    mention = body["mentions"][0]
    assert mention["status"] == "resolved"
    assert mention["job_id"] == "job-abc"
    assert mention["resolved_object"] == {
        "kind": "Deployment", "namespace": "ns", "name": "payment-service"
    }


@patch("api.app.queue")
@patch("api.app.job_store")
@patch("api.app.resolve_mention")
@patch("api.app.decompose_query")
def test_diagnose_query_compound_mixed_outcomes(
    mock_decompose, mock_resolve_mention, mock_job_store, mock_queue
):
    mock_decompose.return_value = [
        DetectedMention(mentioned_service="payment", notes="down"),
        DetectedMention(mentioned_service="secrets", notes="missing"),
    ]
    mock_resolve_mention.side_effect = [
        ObjectRef(kind="Deployment", namespace="ns", name="payment-service"),
        NotFound(),
    ]
    job = MagicMock(job_id="job-abc")
    mock_job_store.create_job.return_value = job
    mock_queue.count = 0

    response = client.post(
        "/diagnose/query",
        json={"query": "payment is down, also secrets missing"},
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 200
    mentions = response.json()["mentions"]
    assert len(mentions) == 2
    assert mentions[0]["status"] == "resolved"
    assert mentions[0]["job_id"] == "job-abc"
    assert mentions[1]["status"] == "not_found"
    assert mentions[1]["job_id"] is None
    # one mention failing to resolve doesn't block the other's job
    mock_job_store.create_job.assert_called_once()


@patch("api.app.resolve_mention")
@patch("api.app.decompose_query")
def test_diagnose_query_ambiguous_mention_lists_candidates(
    mock_decompose, mock_resolve_mention
):
    mock_decompose.return_value = [DetectedMention(mentioned_service="payment", notes=None)]
    mock_resolve_mention.return_value = AmbiguousMatch(
        candidates=[
            ObjectRef(kind="Deployment", namespace="prod", name="payment-service"),
            ObjectRef(kind="Deployment", namespace="staging", name="payment-service"),
        ]
    )

    response = client.post(
        "/diagnose/query", json={"query": "payment is down"}, headers=AUTH_HEADERS
    )

    assert response.status_code == 200
    mention = response.json()["mentions"][0]
    assert mention["status"] == "ambiguous"
    assert mention["job_id"] is None
    assert len(mention["candidates"]) == 2


def test_diagnose_query_without_token_is_401():
    response = client.post("/diagnose/query", json={"query": "payment is down"})
    assert response.status_code == 401


def test_ui_served_without_auth():
    response = client.get("/ui/")
    assert response.status_code == 200
    assert "Incident Agent" in response.text


def test_ui_mount_does_not_open_api_routes():
    assert client.get("/diagnose/some-job").status_code == 401


def test_frontend_never_uses_innerhtml():
    # Chunk text is user-authored and untrusted (spec 010): the UI must
    # render it with textContent only.
    from pathlib import Path

    source = (Path(__file__).parent.parent / "frontend" / "app.js").read_text()
    assert "innerHTML" not in source
    assert "insertAdjacentHTML" not in source
