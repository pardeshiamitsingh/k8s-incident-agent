"""Live end-to-end smoke test for the HTTP API (spec 007).

Spins up a real `uvicorn` process (matching how this actually runs) and
drives it over real HTTP, against a live fixture. Requires a live
kind/minikube cluster and a local Ollama server -- not run by default:

    uv run pytest -m "integration and requires_ollama" tests/integration/test_api_smoke.py
"""

import os
import subprocess
import time
from pathlib import Path

import httpx
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.requires_ollama]

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
def api_server():
    env = {**os.environ, "INCIDENT_AGENT_API_TOKEN": API_TOKEN}
    proc = subprocess.Popen(
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
        yield BASE_URL
    finally:
        proc.terminate()
        proc.wait(timeout=10)


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
