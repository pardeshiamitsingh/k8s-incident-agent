"""Incident intake resolution (spec 005).

Transport-agnostic: spec 007's HTTP handler calls `resolve_intake()`
directly and maps a `ResolutionError` to an HTTP 4xx. No CLI or API
concerns belong in this module.
"""

import logging

from kubernetes.client.exceptions import ApiException

from collectors.k8s_client import build_api_client, build_apps_api_client
from collectors.models import ObjectRef

from .models import IntakeRequest, ResolutionError

logger = logging.getLogger(__name__)


def resolve_intake(request: IntakeRequest) -> ObjectRef | ResolutionError:
    """Resolves an `IntakeRequest` to exactly one `ObjectRef`, per spec
    005's algorithm: explicit `kind` bypasses everything else; otherwise
    both kinds are checked and a same-name collision is broken by health,
    not search order."""
    if request.kind is not None:
        return _resolve_single_kind(request)
    return _resolve_either_kind(request)


def _resolve_single_kind(request: IntakeRequest) -> ObjectRef | ResolutionError:
    if request.kind == "Pod":
        if _get_pod(request.namespace, request.name) is None:
            return _not_found(request, ["Pod"])
        return ObjectRef(kind="Pod", namespace=request.namespace, name=request.name)

    if _get_deployment(request.namespace, request.name) is None:
        return _not_found(request, ["Deployment"])
    return ObjectRef(kind="Deployment", namespace=request.namespace, name=request.name)


def _resolve_either_kind(request: IntakeRequest) -> ObjectRef | ResolutionError:
    pod = _get_pod(request.namespace, request.name)
    deployment = _get_deployment(request.namespace, request.name)

    if pod is None and deployment is None:
        return _not_found(request, ["Pod", "Deployment"])
    if pod is not None and deployment is None:
        return ObjectRef(kind="Pod", namespace=request.namespace, name=request.name)
    if deployment is not None and pod is None:
        return ObjectRef(
            kind="Deployment", namespace=request.namespace, name=request.name
        )

    return _break_tie_by_health(request, pod, deployment)


def _break_tie_by_health(request: IntakeRequest, pod, deployment) -> ObjectRef | ResolutionError:
    pod_is_unhealthy = pod_unhealthy(pod)
    deployment_is_unhealthy = deployment_unhealthy(deployment)
    logger.info(
        "same-name collision for %s/%s: pod_unhealthy=%s deployment_unhealthy=%s",
        request.namespace, request.name, pod_is_unhealthy, deployment_is_unhealthy,
    )

    if pod_is_unhealthy and not deployment_is_unhealthy:
        return ObjectRef(kind="Pod", namespace=request.namespace, name=request.name)
    if deployment_is_unhealthy and not pod_is_unhealthy:
        return ObjectRef(
            kind="Deployment", namespace=request.namespace, name=request.name
        )

    return ResolutionError(
        reason="ambiguous",
        message=(
            f"Both a Pod and a Deployment named '{request.name}' exist in "
            f"namespace '{request.namespace}', and health doesn't disambiguate "
            f"(pod_unhealthy={pod_is_unhealthy}, deployment_unhealthy="
            f"{deployment_is_unhealthy}) -- specify kind explicitly."
        ),
    )


def _not_found(request: IntakeRequest, kinds_checked: list[str]) -> ResolutionError:
    message = (
        f"No object named '{request.name}' found in namespace "
        f"'{request.namespace}' (checked: {', '.join(kinds_checked)})"
    )
    logger.info(message)
    return ResolutionError(reason="not_found", message=message)


def _get_pod(namespace: str, name: str):
    api = build_api_client()
    try:
        return api.read_namespaced_pod(name, namespace)
    except ApiException as exc:
        if exc.status == 404:
            return None
        raise


def _get_deployment(namespace: str, name: str):
    apps_api = build_apps_api_client()
    try:
        return apps_api.read_namespaced_deployment(name, namespace)
    except ApiException as exc:
        if exc.status == 404:
            return None
        raise


def pod_unhealthy(pod) -> bool:
    if pod.status.phase not in ("Running", "Succeeded"):
        return True
    return any(not cs.ready for cs in pod.status.container_statuses or [])


def deployment_unhealthy(deployment) -> bool:
    replicas = deployment.status.replicas or 0
    ready_replicas = deployment.status.ready_replicas or 0
    return ready_replicas != replicas
