"""Describe-equivalent snapshot for a single object (spec 001).

A Pod's snapshot reflects its own runtime state. A Deployment has no
runtime containers of its own -- its `container_statuses` is always empty;
per-Pod container state is what `IncidentEvidence.pods` carries.
"""

import logging

from .k8s_client import build_api_client, build_apps_api_client
from .models import (
    ContainerState,
    ContainerStatus,
    ObjectCondition,
    ObjectDescribeSnapshot,
    ObjectRef,
    OwnerReference,
)

logger = logging.getLogger(__name__)


def get_describe(object_ref: ObjectRef) -> ObjectDescribeSnapshot:
    logger.debug(
        "describing %s %s/%s", object_ref.kind, object_ref.namespace, object_ref.name
    )
    if object_ref.kind == "Pod":
        return _describe_pod(object_ref)
    return _describe_deployment(object_ref)


def _describe_pod(object_ref: ObjectRef) -> ObjectDescribeSnapshot:
    api = build_api_client()
    pod = api.read_namespaced_pod(object_ref.name, object_ref.namespace)

    resources_by_container = {
        c.name: c.resources for c in (pod.spec.containers or [])
    }
    container_statuses = [
        ContainerStatus(
            name=cs.name,
            state=_extract_container_state(cs.state),
            restart_count=cs.restart_count,
            image=cs.image,
            resource_requests=_stringify_resources(
                getattr(resources_by_container.get(cs.name), "requests", None)
            ),
            resource_limits=_stringify_resources(
                getattr(resources_by_container.get(cs.name), "limits", None)
            ),
        )
        for cs in (pod.status.container_statuses or [])
    ]

    phase = pod.status.phase or "Unknown"
    logger.debug(
        "pod %s/%s phase=%s container_states=%s",
        object_ref.namespace, object_ref.name, phase,
        {cs.name: cs.state.phase for cs in container_statuses},
    )
    return ObjectDescribeSnapshot(
        phase=phase,
        conditions=_extract_conditions(pod.status.conditions),
        container_statuses=container_statuses,
        owner_references=_extract_owner_references(pod.metadata.owner_references),
    )


def _describe_deployment(object_ref: ObjectRef) -> ObjectDescribeSnapshot:
    apps_api = build_apps_api_client()
    deployment = apps_api.read_namespaced_deployment(
        object_ref.name, object_ref.namespace
    )

    conditions = _extract_conditions(deployment.status.conditions)
    phase = _deployment_phase(conditions)
    logger.debug(
        "deployment %s/%s phase=%s", object_ref.namespace, object_ref.name, phase
    )
    return ObjectDescribeSnapshot(
        phase=phase,
        conditions=conditions,
        container_statuses=[],
        owner_references=_extract_owner_references(
            deployment.metadata.owner_references
        ),
    )


def _deployment_phase(conditions: list[ObjectCondition]) -> str:
    if any(c.type == "Available" and c.status == "True" for c in conditions):
        return "Available"
    if any(c.type == "Progressing" and c.status == "False" for c in conditions):
        return "Failed"
    return "Progressing"


def _extract_container_state(state) -> ContainerState:
    if state.running is not None:
        return ContainerState(phase="running")
    if state.waiting is not None:
        return ContainerState(
            phase="waiting", reason=state.waiting.reason, message=state.waiting.message
        )
    if state.terminated is not None:
        return ContainerState(
            phase="terminated",
            reason=state.terminated.reason,
            message=state.terminated.message,
        )
    return ContainerState(phase="waiting")


def _stringify_resources(resources) -> dict[str, str]:
    if not resources:
        return {}
    return dict(resources)


def _extract_conditions(conditions) -> list[ObjectCondition]:
    return [
        ObjectCondition(
            type=c.type, status=c.status, reason=c.reason, message=c.message
        )
        for c in (conditions or [])
    ]


def _extract_owner_references(owner_references) -> list[OwnerReference]:
    return [
        OwnerReference(
            kind=ref.kind,
            name=ref.name,
            uid=ref.uid,
            controller=bool(ref.controller),
        )
        for ref in (owner_references or [])
    ]
