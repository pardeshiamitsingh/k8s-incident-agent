"""Runs the full Phase 3 agent graph against live fixtures (spec 003
acceptance criteria).

Requires both a live kind/minikube cluster and a local Ollama server with
llama3.1:8b pulled -- not run by default:

    uv run pytest -m "integration and requires_ollama" tests/integration/test_agent_smoke.py
"""

import subprocess
import time
from pathlib import Path

import pytest

from agent.graph import run_agent
from collectors.collect import collect_evidence
from collectors.models import ObjectRef

pytestmark = [pytest.mark.integration, pytest.mark.requires_ollama]

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "broken-deployments"
NAMESPACE = "agent-fixtures-it"


def _kubectl(*args: str) -> str:
    result = subprocess.run(
        ["kubectl", *args], check=True, capture_output=True, text=True
    )
    return result.stdout


@pytest.fixture(scope="module", autouse=True)
def fixtures_namespace():
    _kubectl("create", "namespace", NAMESPACE)
    for manifest in sorted(FIXTURES_DIR.glob("*.yaml")):
        _kubectl("apply", "-n", NAMESPACE, "-f", str(manifest))
    yield NAMESPACE
    _kubectl("delete", "namespace", NAMESPACE, "--ignore-not-found", "--wait=false")


def _poll(fn, predicate, timeout: float, interval: float = 5):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = fn()
        if predicate(last):
            return last
        time.sleep(interval)
    pytest.fail(f"condition not met within {timeout}s; last value: {last!r}")


def _pod_name(label_selector: str) -> str | None:
    out = _kubectl(
        "get", "pods", "-n", NAMESPACE, "-l", label_selector,
        "-o", "jsonpath={.items[0].metadata.name}",
    ).strip()
    return out or None


def _wait_for_pod_reason(label_selector: str, ready_predicate) -> None:
    pod_name = _poll(lambda: _pod_name(label_selector), predicate=bool, timeout=60)
    ref = ObjectRef(kind="Pod", namespace=NAMESPACE, name=pod_name)
    _poll(lambda: collect_evidence(ref), predicate=ready_predicate, timeout=180)


def _run_agent_for_deployment(name: str):
    return run_agent(ObjectRef(kind="Deployment", namespace=NAMESPACE, name=name))


def test_oom_killed_diagnosis():
    # Wait for the *current* state to actually be OOMKilled, not just for
    # restart_count > 0 -- K8s sets state to waiting/CrashLoopBackOff for
    # the backoff duration after *any* restart, regardless of why the
    # container died, so restart_count > 0 alone doesn't guarantee the
    # reason we're actually testing for is still visible (see spec 001's
    # own oom-killed integration test, which hits the same race and
    # deliberately avoids asserting on the transient reason for it).
    _wait_for_pod_reason(
        "app=oom-killed",
        lambda e: any(
            cs.state.reason == "OOMKilled" for cs in e.describe.container_statuses
        ),
    )
    result = _run_agent_for_deployment("oom-killed")

    # Between the wait above and run_agent's own fresh collect_evidence()
    # call, the container can legitimately cycle into CrashLoopBackOff
    # backoff before OOMKilled reappears on its next death -- both are
    # truthful classifications of this fixture at any given moment, so
    # accept either rather than requiring the exact instant to line up.
    assert set(result.classified_failure_classes) & {"OOMKilled", "CrashLoopBackOff"}
    assert any(
        c.source_file in ("oom-killed.md", "crash-loop-backoff.md")
        for c in result.retrieved_chunks
    )
    assert result.diagnosis.root_cause
    assert result.diagnosis.cited_evidence
    assert result.diagnosis.cited_runbook_chunks
    assert result.remediation_plan.steps


def test_image_pull_backoff_diagnosis():
    _wait_for_pod_reason(
        "app=image-pull-backoff",
        lambda e: any(
            cs.state.reason == "ImagePullBackOff" for cs in e.describe.container_statuses
        ),
    )
    result = _run_agent_for_deployment("image-pull-backoff")

    assert result.classified_failure_classes == ["ImagePullBackOff"]
    assert any(
        c.source_file == "image-pull-backoff.md" for c in result.retrieved_chunks
    )
    assert result.diagnosis.root_cause
    assert result.remediation_plan.steps


def test_create_container_config_error_diagnosis():
    _wait_for_pod_reason(
        "app=create-container-config-error",
        lambda e: bool(e.events)
        and any("missing-configmap" in ev.message for ev in e.events),
    )
    result = _run_agent_for_deployment("create-container-config-error")

    assert result.classified_failure_classes == ["CreateContainerConfigError"]
    assert any(
        c.source_file == "create-container-config-error.md"
        for c in result.retrieved_chunks
    )
    assert result.diagnosis.root_cause
    assert result.remediation_plan.steps


def test_pending_unschedulable_diagnosis():
    _wait_for_pod_reason(
        "app=pending-unschedulable",
        lambda e: e.describe.phase == "Pending" and bool(e.events),
    )
    result = _run_agent_for_deployment("pending-unschedulable")

    assert result.classified_failure_classes == ["Pending"]
    assert any(
        c.source_file == "pending-unschedulable.md" for c in result.retrieved_chunks
    )
    assert result.diagnosis.root_cause
    assert result.remediation_plan.steps
