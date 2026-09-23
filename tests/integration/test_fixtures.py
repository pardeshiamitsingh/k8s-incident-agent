"""Runs collect_evidence against each fixture in fixtures/broken-deployments/,
applied to whatever cluster the current kubeconfig context points at.

Requires a live kind/minikube cluster (spec 001's integration-test
acceptance criterion) -- not run by default:

    uv run pytest -m integration tests/integration/
"""

import subprocess
import time
from pathlib import Path

import pytest

from collectors.collect import collect_evidence
from collectors.models import IncidentEvidence, ObjectRef

pytestmark = pytest.mark.integration

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "broken-deployments"
NAMESPACE = "collectors-fixtures-it"


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


def _evidence_for_pod(label_selector: str, ready_predicate) -> IncidentEvidence:
    pod_name = _poll(lambda: _pod_name(label_selector), predicate=bool, timeout=60)
    ref = ObjectRef(kind="Pod", namespace=NAMESPACE, name=pod_name)
    return _poll(lambda: collect_evidence(ref), predicate=ready_predicate, timeout=180)


def test_image_pull_backoff():
    evidence = _evidence_for_pod(
        "app=image-pull-backoff",
        lambda e: any(
            cs.state.reason == "ImagePullBackOff" for cs in e.describe.container_statuses
        ),
    )
    cs = evidence.describe.container_statuses[0]
    assert cs.state.reason == "ImagePullBackOff"
    assert any(
        ev.reason in ("Failed", "ErrImagePull") for ev in evidence.events
    )


def test_oom_killed():
    evidence = _evidence_for_pod(
        "app=oom-killed",
        lambda e: any(
            cs.state.reason == "OOMKilled"
            or (cs.restart_count > 0)
            for cs in e.describe.container_statuses
        ),
    )
    cs = evidence.describe.container_statuses[0]
    assert cs.restart_count > 0
    assert evidence.logs[cs.name].previous


def test_create_container_config_error():
    evidence = _evidence_for_pod(
        "app=create-container-config-error",
        lambda e: bool(e.events)
        and any("missing-configmap" in ev.message for ev in e.events),
    )
    assert any("missing-configmap" in ev.message for ev in evidence.events)
    assert all(
        cs.state.phase != "running" for cs in evidence.describe.container_statuses
    )


def test_pending_unschedulable():
    evidence = _evidence_for_pod(
        "app=pending-unschedulable",
        lambda e: e.describe.phase == "Pending" and bool(e.events),
    )
    assert evidence.describe.phase == "Pending"
    assert any(ev.reason == "FailedScheduling" for ev in evidence.events)


def test_deployment_expands_to_owned_pods():
    ref = ObjectRef(kind="Deployment", namespace=NAMESPACE, name="pending-unschedulable")
    evidence = _poll(
        lambda: collect_evidence(ref), predicate=lambda e: len(e.pods) == 1, timeout=60
    )
    assert evidence.logs == {}
    assert evidence.pods[0].object_ref.kind == "Pod"
    assert evidence.pods[0].pods == []
