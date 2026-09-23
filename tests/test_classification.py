from datetime import datetime, timezone

from agent.classification import UNKNOWN, classify_evidence
from collectors.models import (
    ContainerState,
    ContainerStatus,
    IncidentEvidence,
    K8sEvent,
    ObjectDescribeSnapshot,
    ObjectRef,
)

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _evidence(
    kind="Pod",
    name="p",
    container_reason=None,
    event_reason=None,
    pods=None,
) -> IncidentEvidence:
    container_statuses = []
    if container_reason:
        container_statuses.append(
            ContainerStatus(
                name="app",
                state=ContainerState(phase="waiting", reason=container_reason),
                restart_count=0,
                image="x",
            )
        )
    events = []
    if event_reason:
        events.append(
            K8sEvent(
                reason=event_reason,
                message="msg",
                type="Warning",
                count=1,
                first_seen=NOW,
                last_seen=NOW,
            )
        )
    return IncidentEvidence(
        object_ref=ObjectRef(kind=kind, namespace="ns", name=name),
        collected_at=NOW,
        events=events,
        describe=ObjectDescribeSnapshot(
            phase="Running", container_statuses=container_statuses
        ),
        logs={},
        pods=pods or [],
    )


def test_classifies_known_container_reason():
    evidence = _evidence(container_reason="OOMKilled")
    assert classify_evidence(evidence) == ["OOMKilled"]


def test_classifies_known_event_reason():
    evidence = _evidence(event_reason="FailedScheduling")
    assert classify_evidence(evidence) == ["Pending"]


def test_maps_err_image_pull_to_image_pull_backoff():
    evidence = _evidence(container_reason="ErrImagePull")
    assert classify_evidence(evidence) == ["ImagePullBackOff"]


def test_unmatched_reason_classifies_as_unknown():
    evidence = _evidence(container_reason="SomeUnrecognizedReason")
    assert classify_evidence(evidence) == [UNKNOWN]


def test_no_reason_at_all_classifies_as_unknown():
    evidence = _evidence()
    assert classify_evidence(evidence) == [UNKNOWN]


def test_deployment_aggregates_distinct_classes_across_pods():
    pod_a = _evidence(name="pod-a", container_reason="OOMKilled")
    pod_b = _evidence(name="pod-b", container_reason="CrashLoopBackOff")
    deployment_evidence = _evidence(
        kind="Deployment", name="d", pods=[pod_a, pod_b]
    )

    result = classify_evidence(deployment_evidence)

    assert result == ["CrashLoopBackOff", "OOMKilled"]


def test_deployment_dedupes_same_class_across_pods():
    pod_a = _evidence(name="pod-a", container_reason="OOMKilled")
    pod_b = _evidence(name="pod-b", container_reason="OOMKilled")
    deployment_evidence = _evidence(
        kind="Deployment", name="d", pods=[pod_a, pod_b]
    )

    assert classify_evidence(deployment_evidence) == ["OOMKilled"]
