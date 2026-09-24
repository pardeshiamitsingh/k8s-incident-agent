"""Live multi-process smoke test for spec 009 (concurrency and scale).

Two API processes + three worker processes, sharing one Redis and one
Chroma running in SERVER mode (not embedded) -- the actual topology this
spec is about, and specifically targeting the landmine it exists to
avoid: multiple worker processes hitting Chroma concurrently must not
reproduce spec 004's embedded-`PersistentClient` stale-read bug.

Requires a live kind/minikube cluster, local Ollama, local Redis, and a
Chroma server already running (`chroma run` or the `chromadb/chroma`
Docker image) on localhost:8000 -- not run by default:

    uv run pytest -m "integration and requires_ollama and requires_redis" tests/integration/test_scale_smoke.py
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
NAMESPACE = "scale-fixtures-it"
API_TOKEN = "scale-test-token"
PORT_A = 8201
PORT_B = 8202
CHROMA_HOST = "localhost"
CHROMA_PORT = 8000


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


def _wait_healthy(base_url: str, timeout: float = 30) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if httpx.get(f"{base_url}/healthz", timeout=1).status_code == 200:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(1)
    return False


@pytest.fixture(scope="module")
def scaled_deployment():
    env = {
        **os.environ,
        "INCIDENT_AGENT_API_TOKEN": API_TOKEN,
        "INCIDENT_AGENT_CHROMA_HOST": CHROMA_HOST,
        "INCIDENT_AGENT_CHROMA_PORT": str(CHROMA_PORT),
    }

    # Ingest into the same server-mode collection every process below
    # will read from.
    previous_host = os.environ.get("INCIDENT_AGENT_CHROMA_HOST")
    previous_port = os.environ.get("INCIDENT_AGENT_CHROMA_PORT")
    os.environ["INCIDENT_AGENT_CHROMA_HOST"] = CHROMA_HOST
    os.environ["INCIDENT_AGENT_CHROMA_PORT"] = str(CHROMA_PORT)
    try:
        ingest_runbooks()
    finally:
        if previous_host is None:
            os.environ.pop("INCIDENT_AGENT_CHROMA_HOST", None)
        else:
            os.environ["INCIDENT_AGENT_CHROMA_HOST"] = previous_host
        if previous_port is None:
            os.environ.pop("INCIDENT_AGENT_CHROMA_PORT", None)
        else:
            os.environ["INCIDENT_AGENT_CHROMA_PORT"] = previous_port

    procs = []
    try:
        for port in (PORT_A, PORT_B):
            procs.append(subprocess.Popen(
                ["uv", "run", "uvicorn", "api.app:app", "--port", str(port), "--log-level", "warning"],
                env=env, cwd=REPO_ROOT,
            ))
        for port in (PORT_A, PORT_B):
            if not _wait_healthy(f"http://127.0.0.1:{port}"):
                pytest.fail(f"API on port {port} did not become healthy in time")

        for _ in range(3):
            procs.append(subprocess.Popen(
                ["uv", "run", "python", "-m", "api.worker"], env=env, cwd=REPO_ROOT,
            ))

        yield {"a": f"http://127.0.0.1:{PORT_A}", "b": f"http://127.0.0.1:{PORT_B}"}
    finally:
        for proc in procs:
            proc.terminate()
        for proc in procs:
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


def test_job_created_on_one_process_visible_on_another(scaled_deployment):
    """Proves job state lives in Redis, not in whichever process created
    it -- the core claim of moving off the in-memory store."""
    _wait_for_pod_oom(NAMESPACE)
    headers = {"Authorization": f"Bearer {API_TOKEN}"}

    response = httpx.post(
        f"{scaled_deployment['a']}/diagnose",
        json={"namespace": NAMESPACE, "name": "oom-killed"},
        headers=headers, timeout=10,
    )
    assert response.status_code == 202
    job_id = response.json()["job_id"]

    # Poll via the OTHER API process entirely.
    result = _poll_job(scaled_deployment["b"], job_id, headers)
    assert result["status"] == "completed"
    assert result["diagnosis"]["root_cause"]


def test_multi_worker_postmortem_retrievable_against_chroma_server(scaled_deployment):
    """The specific landmine this spec exists to avoid: 3 worker
    processes hitting Chroma SERVER mode concurrently must not reproduce
    spec 004's embedded-PersistentClient stale-read bug."""
    _wait_for_pod_oom(NAMESPACE)
    headers = {"Authorization": f"Bearer {API_TOKEN}"}

    first = httpx.post(
        f"{scaled_deployment['a']}/diagnose",
        json={"namespace": NAMESPACE, "name": "oom-killed"},
        headers=headers, timeout=10,
    )
    assert first.status_code == 202
    job_id = first.json()["job_id"]
    first_result = _poll_job(scaled_deployment["a"], job_id, headers)
    assert first_result["status"] == "completed"

    marker = f"scale-marker-{job_id}"
    postmortem = httpx.post(
        f"{scaled_deployment['b']}/diagnose/{job_id}/postmortem",
        json={
            "was_correct": True,
            "actual_root_cause": (
                "Confirmed: the memory limit was undersized for the "
                f"working set, causing repeated OOM kills ({marker})"
            ),
            "actual_fix": "Raised the memory request and limit to 256Mi",
        },
        headers=headers, timeout=10,
    )
    assert postmortem.status_code == 200
    assert postmortem.json() == {"ingested": True}

    second = httpx.post(
        f"{scaled_deployment['b']}/diagnose",
        json={"namespace": NAMESPACE, "name": "oom-killed"},
        headers=headers, timeout=10,
    )
    assert second.status_code == 202
    second_result = _poll_job(scaled_deployment["a"], second.json()["job_id"], headers)
    assert second_result["status"] == "completed"

    assert any(marker in c["text"] for c in second_result["retrieved_chunks"]), (
        f"expected the postmortem chunk (marker={marker!r}) to survive 3 "
        f"concurrent worker processes hitting Chroma server mode, got "
        f"chunk ids: {[c['id'] for c in second_result['retrieved_chunks']]}"
    )
