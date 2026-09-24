from unittest.mock import MagicMock, patch

from kubernetes.client import V1Deployment, V1DeploymentList, V1DeploymentStatus, V1ObjectMeta

from collectors.models import ObjectRef
from nlintake.fuzzy_resolve import fuzzy_candidates, resolve_mention
from nlintake.models import AmbiguousMatch, DetectedMention, NotFound


def _deployment(name, namespace="ns", replicas=3, ready_replicas=3) -> V1Deployment:
    return V1Deployment(
        metadata=V1ObjectMeta(name=name, namespace=namespace),
        status=V1DeploymentStatus(replicas=replicas, ready_replicas=ready_replicas),
    )


@patch("nlintake.fuzzy_resolve.build_apps_api_client")
def test_fuzzy_candidates_substring_match(mock_build_apps):
    apps_api = MagicMock()
    apps_api.list_deployment_for_all_namespaces.return_value = V1DeploymentList(
        items=[_deployment("payment-service"), _deployment("auth-service")]
    )
    mock_build_apps.return_value = apps_api

    result = fuzzy_candidates("payment")

    assert result == [ObjectRef(kind="Deployment", namespace="ns", name="payment-service")]


@patch("nlintake.fuzzy_resolve.build_apps_api_client")
def test_fuzzy_candidates_close_match_fallback(mock_build_apps):
    apps_api = MagicMock()
    apps_api.list_deployment_for_all_namespaces.return_value = V1DeploymentList(
        items=[_deployment("paymnet-svc")]  # typo'd, no substring match
    )
    mock_build_apps.return_value = apps_api

    result = fuzzy_candidates("paymnet")

    assert result == [ObjectRef(kind="Deployment", namespace="ns", name="paymnet-svc")]


@patch("nlintake.fuzzy_resolve.build_apps_api_client")
def test_fuzzy_candidates_no_match(mock_build_apps):
    apps_api = MagicMock()
    apps_api.list_deployment_for_all_namespaces.return_value = V1DeploymentList(
        items=[_deployment("auth-service")]
    )
    mock_build_apps.return_value = apps_api

    assert fuzzy_candidates("completely-unrelated-xyz") == []


@patch("nlintake.fuzzy_resolve.build_apps_api_client")
def test_fuzzy_candidates_namespace_scoped(mock_build_apps):
    apps_api = MagicMock()
    apps_api.list_namespaced_deployment.return_value = V1DeploymentList(
        items=[_deployment("payment-service", namespace="prod")]
    )
    mock_build_apps.return_value = apps_api

    result = fuzzy_candidates("payment", namespace_scope=["prod"])

    apps_api.list_namespaced_deployment.assert_called_once_with("prod")
    apps_api.list_deployment_for_all_namespaces.assert_not_called()
    assert result == [ObjectRef(kind="Deployment", namespace="prod", name="payment-service")]


@patch("nlintake.fuzzy_resolve.resolve_intake")
@patch("nlintake.fuzzy_resolve.build_apps_api_client")
def test_resolve_mention_single_match_resolves(mock_build_apps, mock_resolve_intake):
    apps_api = MagicMock()
    apps_api.list_deployment_for_all_namespaces.return_value = V1DeploymentList(
        items=[_deployment("payment-service")]
    )
    mock_build_apps.return_value = apps_api
    mock_resolve_intake.return_value = ObjectRef(
        kind="Deployment", namespace="ns", name="payment-service"
    )

    result = resolve_mention(DetectedMention(mentioned_service="payment"))

    assert result == ObjectRef(kind="Deployment", namespace="ns", name="payment-service")


@patch("nlintake.fuzzy_resolve.build_apps_api_client")
def test_resolve_mention_no_match_is_not_found(mock_build_apps):
    apps_api = MagicMock()
    apps_api.list_deployment_for_all_namespaces.return_value = V1DeploymentList(items=[])
    mock_build_apps.return_value = apps_api

    result = resolve_mention(DetectedMention(mentioned_service="payment"))

    assert isinstance(result, NotFound)


@patch("nlintake.fuzzy_resolve.resolve_intake")
@patch("nlintake.fuzzy_resolve.build_apps_api_client")
def test_resolve_mention_multiple_matches_health_tie_break(mock_build_apps, mock_resolve_intake):
    apps_api = MagicMock()
    apps_api.list_deployment_for_all_namespaces.return_value = V1DeploymentList(
        items=[
            _deployment("payment-service", namespace="prod", replicas=3, ready_replicas=1),
            _deployment("payment-service", namespace="staging", replicas=3, ready_replicas=3),
        ]
    )
    mock_build_apps.return_value = apps_api
    mock_resolve_intake.return_value = ObjectRef(
        kind="Deployment", namespace="prod", name="payment-service"
    )

    result = resolve_mention(DetectedMention(mentioned_service="payment"))

    assert result == ObjectRef(kind="Deployment", namespace="prod", name="payment-service")


@patch("nlintake.fuzzy_resolve.build_apps_api_client")
def test_resolve_mention_multiple_matches_both_healthy_is_ambiguous(mock_build_apps):
    apps_api = MagicMock()
    apps_api.list_deployment_for_all_namespaces.return_value = V1DeploymentList(
        items=[
            _deployment("payment-service", namespace="prod", replicas=3, ready_replicas=3),
            _deployment("payment-service", namespace="staging", replicas=3, ready_replicas=3),
        ]
    )
    mock_build_apps.return_value = apps_api

    result = resolve_mention(DetectedMention(mentioned_service="payment"))

    assert isinstance(result, AmbiguousMatch)
    assert len(result.candidates) == 2


@patch("nlintake.fuzzy_resolve.build_apps_api_client")
def test_resolve_mention_multiple_matches_both_unhealthy_is_ambiguous(mock_build_apps):
    apps_api = MagicMock()
    apps_api.list_deployment_for_all_namespaces.return_value = V1DeploymentList(
        items=[
            _deployment("payment-service", namespace="prod", replicas=3, ready_replicas=0),
            _deployment("payment-service", namespace="staging", replicas=3, ready_replicas=0),
        ]
    )
    mock_build_apps.return_value = apps_api

    result = resolve_mention(DetectedMention(mentioned_service="payment"))

    assert isinstance(result, AmbiguousMatch)


@patch("nlintake.fuzzy_resolve.resolve_intake")
@patch("nlintake.fuzzy_resolve.build_apps_api_client")
def test_resolve_mention_stale_listing_falls_back_to_not_found(mock_build_apps, mock_resolve_intake):
    from intake.models import ResolutionError

    apps_api = MagicMock()
    apps_api.list_deployment_for_all_namespaces.return_value = V1DeploymentList(
        items=[_deployment("payment-service")]
    )
    mock_build_apps.return_value = apps_api
    mock_resolve_intake.return_value = ResolutionError(reason="not_found", message="gone")

    result = resolve_mention(DetectedMention(mentioned_service="payment"))

    assert isinstance(result, NotFound)
