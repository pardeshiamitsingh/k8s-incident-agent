from unittest.mock import patch

from collectors.collect import collect_evidence
from collectors.models import ObjectDescribeSnapshot, ObjectRef


@patch("collectors.collect.get_logs")
@patch("collectors.collect.get_describe")
@patch("collectors.collect.get_events")
def test_collect_evidence_pod_has_no_pods_field_populated(
    mock_events, mock_describe, mock_logs
):
    mock_events.return_value = []
    mock_describe.return_value = ObjectDescribeSnapshot(phase="Running")
    mock_logs.return_value = {}

    ref = ObjectRef(kind="Pod", namespace="ns", name="my-pod")
    evidence = collect_evidence(ref)

    assert evidence.pods == []
    mock_logs.assert_called_once_with(ref)


@patch("collectors.collect._get_owned_pod_refs")
@patch("collectors.collect.get_logs")
@patch("collectors.collect.get_describe")
@patch("collectors.collect.get_events")
def test_collect_evidence_deployment_expands_owned_pods(
    mock_events, mock_describe, mock_logs, mock_owned_pods
):
    mock_events.return_value = []
    mock_describe.return_value = ObjectDescribeSnapshot(phase="Available")
    mock_logs.return_value = {}
    mock_owned_pods.return_value = [
        ObjectRef(kind="Pod", namespace="ns", name=f"pod-{i}") for i in range(3)
    ]

    ref = ObjectRef(kind="Deployment", namespace="ns", name="my-deploy")
    evidence = collect_evidence(ref)

    assert evidence.logs == {}
    assert len(evidence.pods) == 3
    assert [p.object_ref.name for p in evidence.pods] == [
        "pod-0",
        "pod-1",
        "pod-2",
    ]
    assert all(p.pods == [] for p in evidence.pods)
    # get_logs was called once per owned Pod, never for the Deployment itself.
    assert mock_logs.call_count == 3


@patch("collectors.collect._get_owned_pod_refs")
@patch("collectors.collect.get_logs")
@patch("collectors.collect.get_describe")
@patch("collectors.collect.get_events")
def test_collect_evidence_deployment_no_owned_pods(
    mock_events, mock_describe, mock_logs, mock_owned_pods
):
    mock_events.return_value = []
    mock_describe.return_value = ObjectDescribeSnapshot(phase="Available")
    mock_owned_pods.return_value = []

    ref = ObjectRef(kind="Deployment", namespace="ns", name="my-deploy")
    evidence = collect_evidence(ref)

    assert evidence.pods == []
    mock_logs.assert_not_called()
