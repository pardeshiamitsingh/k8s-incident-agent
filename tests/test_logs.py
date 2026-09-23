from unittest.mock import MagicMock, patch

from kubernetes.client import (
    V1ContainerState,
    V1ContainerStateTerminated,
    V1ContainerStatus,
    V1ObjectMeta,
    V1Pod,
    V1PodStatus,
)
from kubernetes.client.exceptions import ApiException

from collectors.logs import get_logs
from collectors.models import ObjectRef


def _ref() -> ObjectRef:
    return ObjectRef(kind="Pod", namespace="ns", name="my-pod")


@patch("collectors.logs.build_api_client")
def test_get_logs_no_restart_skips_previous(mock_build_client):
    api = MagicMock()
    api.read_namespaced_pod.return_value = V1Pod(
        status=V1PodStatus(
            container_statuses=[
                V1ContainerStatus(name="app", image="x", restart_count=0)
            ]
        )
    )
    api.read_namespaced_pod_log.return_value = "current output"
    mock_build_client.return_value = api

    logs = get_logs(_ref())

    assert logs["app"].current == "current output"
    assert logs["app"].previous is None
    api.read_namespaced_pod_log.assert_called_once_with(
        "my-pod", "ns", container="app", previous=False
    )


@patch("collectors.logs.build_api_client")
def test_get_logs_restarted_fetches_previous(mock_build_client):
    api = MagicMock()
    api.read_namespaced_pod.return_value = V1Pod(
        status=V1PodStatus(
            container_statuses=[
                V1ContainerStatus(
                    name="app",
                    image="x",
                    restart_count=1,
                    last_state=V1ContainerState(
                        terminated=V1ContainerStateTerminated(reason="OOMKilled")
                    ),
                )
            ]
        )
    )
    api.read_namespaced_pod_log.side_effect = ["current output", "previous output"]
    mock_build_client.return_value = api

    logs = get_logs(_ref())

    assert logs["app"].current == "current output"
    assert logs["app"].previous == "previous output"
    assert api.read_namespaced_pod_log.call_count == 2


@patch("collectors.logs.build_api_client")
def test_get_logs_handles_api_exception_as_none(mock_build_client):
    api = MagicMock()
    api.read_namespaced_pod.return_value = V1Pod(
        status=V1PodStatus(
            container_statuses=[
                V1ContainerStatus(name="app", image="x", restart_count=0)
            ]
        )
    )
    api.read_namespaced_pod_log.side_effect = ApiException(status=400)
    mock_build_client.return_value = api

    logs = get_logs(_ref())

    assert logs["app"].current is None
