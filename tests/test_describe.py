from unittest.mock import MagicMock, patch

from kubernetes.client import (
    V1Container,
    V1ContainerState,
    V1ContainerStateTerminated,
    V1ContainerStateWaiting,
    V1ContainerStatus,
    V1Deployment,
    V1DeploymentCondition,
    V1DeploymentStatus,
    V1ObjectMeta,
    V1OwnerReference,
    V1Pod,
    V1PodCondition,
    V1PodSpec,
    V1PodStatus,
    V1ResourceRequirements,
)

from collectors.describe import get_describe
from collectors.models import ObjectRef


def _pod_ref() -> ObjectRef:
    return ObjectRef(kind="Pod", namespace="ns", name="my-pod")


def _deployment_ref() -> ObjectRef:
    return ObjectRef(kind="Deployment", namespace="ns", name="my-deploy")


@patch("collectors.describe.build_api_client")
def test_describe_pod_waiting_container(mock_build_client):
    api = MagicMock()
    api.read_namespaced_pod.return_value = V1Pod(
        metadata=V1ObjectMeta(
            owner_references=[
                V1OwnerReference(
                    kind="ReplicaSet", name="my-deploy-abc", uid="rs-uid", controller=True
                )
            ]
        ),
        spec=V1PodSpec(
            containers=[
                V1Container(
                    name="app",
                    resources=V1ResourceRequirements(
                        requests={"cpu": "100m"}, limits={"memory": "128Mi"}
                    ),
                )
            ]
        ),
        status=V1PodStatus(
            phase="Pending",
            conditions=[
                V1PodCondition(type="Ready", status="False", reason="ContainersNotReady")
            ],
            container_statuses=[
                V1ContainerStatus(
                    name="app",
                    image="broken:v1",
                    restart_count=0,
                    state=V1ContainerState(
                        waiting=V1ContainerStateWaiting(reason="ImagePullBackOff")
                    ),
                )
            ],
        ),
    )
    mock_build_client.return_value = api

    snapshot = get_describe(_pod_ref())

    assert snapshot.phase == "Pending"
    assert snapshot.conditions[0].reason == "ContainersNotReady"
    assert len(snapshot.container_statuses) == 1
    cs = snapshot.container_statuses[0]
    assert cs.state.phase == "waiting"
    assert cs.state.reason == "ImagePullBackOff"
    assert cs.resource_requests == {"cpu": "100m"}
    assert cs.resource_limits == {"memory": "128Mi"}
    assert snapshot.owner_references[0].kind == "ReplicaSet"
    assert snapshot.owner_references[0].controller is True


@patch("collectors.describe.build_api_client")
def test_describe_pod_terminated_container(mock_build_client):
    api = MagicMock()
    api.read_namespaced_pod.return_value = V1Pod(
        metadata=V1ObjectMeta(),
        spec=V1PodSpec(containers=[V1Container(name="app")]),
        status=V1PodStatus(
            phase="Running",
            container_statuses=[
                V1ContainerStatus(
                    name="app",
                    image="app:v1",
                    restart_count=2,
                    state=V1ContainerState(
                        terminated=V1ContainerStateTerminated(reason="OOMKilled")
                    ),
                )
            ],
        ),
    )
    mock_build_client.return_value = api

    snapshot = get_describe(_pod_ref())

    cs = snapshot.container_statuses[0]
    assert cs.state.phase == "terminated"
    assert cs.state.reason == "OOMKilled"
    assert cs.restart_count == 2


@patch("collectors.describe.build_apps_api_client")
def test_describe_deployment_available(mock_build_apps_client):
    apps_api = MagicMock()
    apps_api.read_namespaced_deployment.return_value = V1Deployment(
        metadata=V1ObjectMeta(),
        status=V1DeploymentStatus(
            conditions=[
                V1DeploymentCondition(type="Available", status="True", reason="MinimumReplicasAvailable")
            ]
        ),
    )
    mock_build_apps_client.return_value = apps_api

    snapshot = get_describe(_deployment_ref())

    assert snapshot.phase == "Available"
    assert snapshot.container_statuses == []


@patch("collectors.describe.build_apps_api_client")
def test_describe_deployment_failed_progressing(mock_build_apps_client):
    apps_api = MagicMock()
    apps_api.read_namespaced_deployment.return_value = V1Deployment(
        metadata=V1ObjectMeta(),
        status=V1DeploymentStatus(
            conditions=[
                V1DeploymentCondition(
                    type="Progressing", status="False", reason="ProgressDeadlineExceeded"
                )
            ]
        ),
    )
    mock_build_apps_client.return_value = apps_api

    snapshot = get_describe(_deployment_ref())

    assert snapshot.phase == "Failed"
