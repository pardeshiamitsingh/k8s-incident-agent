from unittest.mock import MagicMock, patch

from kubernetes.client import (
    V1ContainerStatus,
    V1Deployment,
    V1DeploymentStatus,
    V1ObjectMeta,
    V1Pod,
    V1PodStatus,
)
from kubernetes.client.exceptions import ApiException

from intake.models import IntakeRequest, ResolutionError
from intake.resolve import resolve_intake


def _pod(healthy=True) -> V1Pod:
    if healthy:
        status = V1PodStatus(
            phase="Running",
            container_statuses=[V1ContainerStatus(name="app", image="x", ready=True)],
        )
    else:
        status = V1PodStatus(
            phase="Running",
            container_statuses=[V1ContainerStatus(name="app", image="x", ready=False)],
        )
    return V1Pod(metadata=V1ObjectMeta(name="w"), status=status)


def _deployment(healthy=True) -> V1Deployment:
    replicas = 3
    ready = 3 if healthy else 1
    return V1Deployment(
        metadata=V1ObjectMeta(name="w"),
        status=V1DeploymentStatus(replicas=replicas, ready_replicas=ready),
    )


def _not_found_exc() -> ApiException:
    return ApiException(status=404)


@patch("intake.resolve.build_apps_api_client")
@patch("intake.resolve.build_api_client")
def test_kind_given_found(mock_core, mock_apps):
    api = MagicMock()
    api.read_namespaced_pod.return_value = _pod()
    mock_core.return_value = api

    result = resolve_intake(IntakeRequest(namespace="ns", name="x", kind="Pod"))

    assert result.kind == "Pod"
    assert result.name == "x"


@patch("intake.resolve.build_apps_api_client")
@patch("intake.resolve.build_api_client")
def test_kind_given_not_found(mock_core, mock_apps):
    api = MagicMock()
    api.read_namespaced_pod.side_effect = _not_found_exc()
    mock_core.return_value = api

    result = resolve_intake(IntakeRequest(namespace="ns", name="x", kind="Pod"))

    assert isinstance(result, ResolutionError)
    assert result.reason == "not_found"


@patch("intake.resolve.build_apps_api_client")
@patch("intake.resolve.build_api_client")
def test_only_pod_exists_resolves_to_pod(mock_core, mock_apps):
    core = MagicMock()
    core.read_namespaced_pod.return_value = _pod()
    mock_core.return_value = core
    apps = MagicMock()
    apps.read_namespaced_deployment.side_effect = _not_found_exc()
    mock_apps.return_value = apps

    result = resolve_intake(IntakeRequest(namespace="ns", name="x"))

    assert result.kind == "Pod"


@patch("intake.resolve.build_apps_api_client")
@patch("intake.resolve.build_api_client")
def test_only_deployment_exists_resolves_to_deployment(mock_core, mock_apps):
    core = MagicMock()
    core.read_namespaced_pod.side_effect = _not_found_exc()
    mock_core.return_value = core
    apps = MagicMock()
    apps.read_namespaced_deployment.return_value = _deployment()
    mock_apps.return_value = apps

    result = resolve_intake(IntakeRequest(namespace="ns", name="y"))

    assert result.kind == "Deployment"


@patch("intake.resolve.build_apps_api_client")
@patch("intake.resolve.build_api_client")
def test_neither_exists_not_found(mock_core, mock_apps):
    core = MagicMock()
    core.read_namespaced_pod.side_effect = _not_found_exc()
    mock_core.return_value = core
    apps = MagicMock()
    apps.read_namespaced_deployment.side_effect = _not_found_exc()
    mock_apps.return_value = apps

    result = resolve_intake(IntakeRequest(namespace="ns", name="z"))

    assert isinstance(result, ResolutionError)
    assert result.reason == "not_found"


@patch("intake.resolve.build_apps_api_client")
@patch("intake.resolve.build_api_client")
def test_collision_only_pod_unhealthy_resolves_to_pod(mock_core, mock_apps):
    core = MagicMock()
    core.read_namespaced_pod.return_value = _pod(healthy=False)
    mock_core.return_value = core
    apps = MagicMock()
    apps.read_namespaced_deployment.return_value = _deployment(healthy=True)
    mock_apps.return_value = apps

    result = resolve_intake(IntakeRequest(namespace="ns", name="w"))

    assert result.kind == "Pod"


@patch("intake.resolve.build_apps_api_client")
@patch("intake.resolve.build_api_client")
def test_collision_only_deployment_unhealthy_resolves_to_deployment(mock_core, mock_apps):
    core = MagicMock()
    core.read_namespaced_pod.return_value = _pod(healthy=True)
    mock_core.return_value = core
    apps = MagicMock()
    apps.read_namespaced_deployment.return_value = _deployment(healthy=False)
    mock_apps.return_value = apps

    result = resolve_intake(IntakeRequest(namespace="ns", name="w"))

    assert result.kind == "Deployment"


@patch("intake.resolve.build_apps_api_client")
@patch("intake.resolve.build_api_client")
def test_collision_both_healthy_is_ambiguous(mock_core, mock_apps):
    core = MagicMock()
    core.read_namespaced_pod.return_value = _pod(healthy=True)
    mock_core.return_value = core
    apps = MagicMock()
    apps.read_namespaced_deployment.return_value = _deployment(healthy=True)
    mock_apps.return_value = apps

    result = resolve_intake(IntakeRequest(namespace="ns", name="w"))

    assert isinstance(result, ResolutionError)
    assert result.reason == "ambiguous"


@patch("intake.resolve.build_apps_api_client")
@patch("intake.resolve.build_api_client")
def test_collision_both_unhealthy_is_ambiguous(mock_core, mock_apps):
    core = MagicMock()
    core.read_namespaced_pod.return_value = _pod(healthy=False)
    mock_core.return_value = core
    apps = MagicMock()
    apps.read_namespaced_deployment.return_value = _deployment(healthy=False)
    mock_apps.return_value = apps

    result = resolve_intake(IntakeRequest(namespace="ns", name="w"))

    assert isinstance(result, ResolutionError)
    assert result.reason == "ambiguous"
