"""Live end-to-end smoke test for the HTTP API (spec 007, spec 009).

Spins up a real `uvicorn` process plus a real `api.worker` process
(matching how this actually runs since spec 009 -- an enqueued job does
nothing without a worker consuming the queue) and drives it over real
HTTP, against a live fixture. Requires a live kind/minikube cluster, a
local Ollama server, and a local Redis -- not run by default:

    uv run pytest -m "integration and requires_ollama and requires_redis" tests/integration/test_api_smoke.py
"""

import os
import subprocess
import time
from pathlib import Path

import httpx
import pytest

from knowledge_base.ingest import ingest_runbooks

pytestmark = [pytest.mark.integration, pytest.mark.requires_ollama, pytest.mark.requires_redis]

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_DIR = REPO_ROOT / "fixtures" / "broken-deployments"
NAMESPACE = "api-fixtures-it"
API_TOKEN = "integration-test-token"
PORT = 8199
BASE_URL = f"http://127.0.0.1:{PORT}"


def _kubectl(*args: str) -> str:
    result = subprocess.run(
        ["kubectl", *args], check=True, capture_output=True, text=True
    )
    return result.stdout


@pytest.fixture(scope="module", autouse=True)
def fixtures_namespace():
    _kubectl("create", "namespace", NAMESPACE)
    _kubectl("apply", "-n", NAMESPACE, "-f", str(FIXTURES_DIR / "oom-killed.yaml"))
    yield NAMESPACE
    _kubectl("delete", "namespace", NAMESPACE, "--ignore-not-found", "--wait=false")


@pytest.fixture(scope="module")
def api_server(tmp_path_factory):
    # Isolated Chroma store for the whole fixture lifetime (setup, the
    # server subprocess, AND any in-process retrieve_runbooks() calls the
    # test body makes directly) -- this test writes real postmortem
    # chunks (test_postmortem_flow_makes_content_retrievable), and the
    # dev '.chroma/' directory must never accumulate test-run garbage.
    # Discovered the hard way: a stale chunk from a prior run pushed this
    # run's own chunk out of the top-k on a later, unrelated test run.
    chroma_path = tmp_path_factory.mktemp("chroma")
    previous = os.environ.get("INCIDENT_AGENT_CHROMA_PATH")
    os.environ["INCIDENT_AGENT_CHROMA_PATH"] = str(chroma_path)
    try:
        ingest_runbooks()

        env = {**os.environ, "INCIDENT_AGENT_API_TOKEN": API_TOKEN}
        api_proc = subprocess.Popen(
            [
                "uv", "run", "uvicorn", "api.app:app",
                "--port", str(PORT), "--log-level", "warning",
            ],
            env=env,
            cwd=REPO_ROOT,
        )
        try:
            deadline = time.monotonic() + 30
            healthy = False
            while time.monotonic() < deadline:
                try:
                    if httpx.get(f"{BASE_URL}/healthz", timeout=1).status_code == 200:
                        healthy = True
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(1)
            if not healthy:
                pytest.fail("API server did not become healthy in time")

            # Spec 009: an enqueued job does nothing without a worker
            # process consuming the queue -- same env (same isolated
            # Chroma path, same Redis) as the API process.
            worker_proc = subprocess.Popen(
                ["uv", "run", "python", "-m", "api.worker"],
                env=env,
                cwd=REPO_ROOT,
            )
            try:
                yield BASE_URL
            finally:
                worker_proc.terminate()
                worker_proc.wait(timeout=10)
        finally:
            api_proc.terminate()
            api_proc.wait(timeout=10)
    finally:
        if previous is None:
            os.environ.pop("INCIDENT_AGENT_CHROMA_PATH", None)
        else:
            os.environ["INCIDENT_AGENT_CHROMA_PATH"] = previous


def _wait_for_pod_oom(namespace: str, timeout: float = 60) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        out = _kubectl(
            "get", "pods", "-n", namespace, "-l", "app=oom-killed",
            "-o", "jsonpath={.items[0].status.containerStatuses[0].state.terminated.reason}",
        ).strip()
        if out == "OOMKilled":
            return
        time.sleep(2)
    pytest.fail("pod did not reach OOMKilled in time")


def _poll_job(base_url: str, job_id: str, headers: dict, timeout: float = 180) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = httpx.get(f"{base_url}/diagnose/{job_id}", headers=headers, timeout=10)
        body = response.json()
        if body["status"] in ("completed", "failed"):
            return body
        time.sleep(3)
    pytest.fail(f"job {job_id} did not complete within {timeout}s")


def test_unauthenticated_request_rejected(api_server):
    response = httpx.post(
        f"{api_server}/diagnose",
        json={"namespace": NAMESPACE, "name": "oom-killed"},
        timeout=10,
    )
    assert response.status_code == 401


def test_not_found_request(api_server):
    headers = {"Authorization": f"Bearer {API_TOKEN}"}
    response = httpx.post(
        f"{api_server}/diagnose",
        json={"namespace": NAMESPACE, "name": "does-not-exist"},
        headers=headers,
        timeout=10,
    )
    assert response.status_code == 404


def test_full_http_flow_against_oom_killed_fixture(api_server):
    _wait_for_pod_oom(NAMESPACE)
    headers = {"Authorization": f"Bearer {API_TOKEN}"}

    response = httpx.post(
        f"{api_server}/diagnose",
        json={"namespace": NAMESPACE, "name": "oom-killed"},
        headers=headers,
        timeout=10,
    )
    assert response.status_code == 202
    job_id = response.json()["job_id"]

    result = _poll_job(api_server, job_id, headers)

    assert result["status"] == "completed"
    # See agent's own oom-killed test for why both labels are accepted.
    assert set(result["classified_failure_classes"]) & {"OOMKilled", "CrashLoopBackOff"}
    assert any(
        c["source_file"] in ("oom-killed.md", "crash-loop-backoff.md")
        for c in result["retrieved_chunks"]
    )
    assert result["diagnosis"]["root_cause"]
    assert result["diagnosis"]["cited_evidence"]
    assert result["diagnosis"]["cited_runbook_chunks"]
    assert result["remediation_plan"]["steps"]


def test_postmortem_flow_makes_content_retrievable(api_server):
    """spec 004's core acceptance criterion: a correct postmortem becomes
    retrievable via spec 002's unchanged retrieve_runbooks(), with no
    Phase 3 code needing to change.

    Verifies this by triggering a *second* /diagnose run for the same
    object and checking its retrieved_chunks, rather than calling
    retrieve_runbooks() directly from the test process -- Chroma's
    PersistentClient isn't reliably consistent when a separate, still-live
    process reads while the API subprocess may not have flushed its
    write yet. Going through a second real request keeps everything
    inside the one process that did the writing, and is also a more
    realistic test of the actual feature: does a later diagnosis for a
    similar incident actually pick up the postmortem?
    """
    _wait_for_pod_oom(NAMESPACE)
    headers = {"Authorization": f"Bearer {API_TOKEN}"}

    first = httpx.post(
        f"{api_server}/diagnose",
        json={"namespace": NAMESPACE, "name": "oom-killed"},
        headers=headers,
        timeout=10,
    )
    assert first.status_code == 202
    job_id = first.json()["job_id"]

    first_result = _poll_job(api_server, job_id, headers)
    assert first_result["status"] == "completed"

    # Realistic content matters here, not just a placeholder -- retrieval
    # is embedding-similarity-based, and a content-free marker string
    # embeds nowhere near "OOMKilled" semantically, so it wouldn't rank in
    # the top-k regardless of whether ingestion worked. A real human
    # postmortem submission would naturally read like this anyway.
    marker = f"unique-marker-{job_id}"
    postmortem_response = httpx.post(
        f"{api_server}/diagnose/{job_id}/postmortem",
        json={
            "was_correct": True,
            "actual_root_cause": (
                "Confirmed: the container's memory limit was undersized for "
                f"its actual working set, causing repeated OOM kills ({marker})"
            ),
            "actual_fix": "Raised the memory request and limit to 256Mi, which resolved the OOM kills",
        },
        headers=headers,
        timeout=10,
    )
    assert postmortem_response.status_code == 200
    assert postmortem_response.json() == {"ingested": True}

    second = httpx.post(
        f"{api_server}/diagnose",
        json={"namespace": NAMESPACE, "name": "oom-killed"},
        headers=headers,
        timeout=10,
    )
    assert second.status_code == 202
    second_result = _poll_job(api_server, second.json()["job_id"], headers)
    assert second_result["status"] == "completed"

    assert any(marker in c["text"] for c in second_result["retrieved_chunks"]), (
        f"expected the postmortem chunk (marker={marker!r}) to be retrieved by a "
        f"second diagnosis of the same object, got chunk ids: "
        f"{[c['id'] for c in second_result['retrieved_chunks']]}"
    )


def test_natural_language_query_resolves_and_diagnoses(api_server):
    """spec 008 end to end: free text -> decomposition -> fuzzy match ->
    the same job/poll flow every other entrypoint already uses."""
    _wait_for_pod_oom(NAMESPACE)
    headers = {"Authorization": f"Bearer {API_TOKEN}"}

    # Phrased so "oom-killed" reads as the service's name, not a symptom
    # description -- "my oom-killed deployment" gets (correctly) parsed as
    # someone describing an OOM symptom, not naming an object literally
    # called "oom-killed", which real object names essentially never are.
    response = httpx.post(
        f"{api_server}/diagnose/query",
        json={"query": "the service named oom-killed is broken, please diagnose it"},
        headers=headers,
        timeout=30,
    )
    assert response.status_code == 200
    mentions = response.json()["mentions"]
    assert mentions, "expected at least one detected mention"

    resolved = [m for m in mentions if m["status"] == "resolved"]
    assert resolved, f"expected at least one resolved mention, got {mentions}"
    match = resolved[0]
    assert match["resolved_object"]["name"] == "oom-killed"
    assert match["resolved_object"]["namespace"] == NAMESPACE
    assert match["job_id"]

    result = _poll_job(api_server, match["job_id"], headers)
    assert result["status"] == "completed"
    assert set(result["classified_failure_classes"]) & {"OOMKilled", "CrashLoopBackOff"}
    assert result["diagnosis"]["root_cause"]
    assert result["remediation_plan"]["steps"]
