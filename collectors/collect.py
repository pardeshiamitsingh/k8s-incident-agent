"""The single entrypoint later phases should import (spec 001)."""

import logging
from datetime import datetime, timezone

from .describe import get_describe
from .events import get_events
from .k8s_client import build_api_client, build_apps_api_client
from .logs import get_logs
from .models import IncidentEvidence, ObjectRef

logger = logging.getLogger(__name__)


def collect_evidence(object_ref: ObjectRef) -> IncidentEvidence:
    logger.info(
        "collecting evidence for %s %s/%s",
        object_ref.kind, object_ref.namespace, object_ref.name,
    )
    events = get_events(object_ref)
    describe = get_describe(object_ref)

    if object_ref.kind == "Pod":
        logs = get_logs(object_ref)
        pods: list[IncidentEvidence] = []
    else:
        logs = {}
        owned_pod_refs = _get_owned_pod_refs(object_ref)
        logger.info(
            "deployment %s/%s owns %d pod(s): %s",
            object_ref.namespace, object_ref.name, len(owned_pod_refs),
            [ref.name for ref in owned_pod_refs],
        )
        pods = [collect_evidence(pod_ref) for pod_ref in owned_pod_refs]

    return IncidentEvidence(
        object_ref=object_ref,
        collected_at=datetime.now(timezone.utc),
        events=events,
        describe=describe,
        logs=logs,
        pods=pods,
    )


def _get_owned_pod_refs(deployment_ref: ObjectRef) -> list[ObjectRef]:
    """Deployment -> owned ReplicaSet(s) -> owned Pod(s), via owner reference."""
    apps_api = build_apps_api_client()
    core_api = build_api_client()

    deployment = apps_api.read_namespaced_deployment(
        deployment_ref.name, deployment_ref.namespace
    )
    deployment_uid = deployment.metadata.uid

    replica_sets = apps_api.list_namespaced_replica_set(deployment_ref.namespace)
    owned_rs_uids = {
        rs.metadata.uid
        for rs in replica_sets.items
        if any(
            ref.uid == deployment_uid for ref in (rs.metadata.owner_references or [])
        )
    }
    logger.debug(
        "deployment %s/%s owns %d replicaset(s)",
        deployment_ref.namespace, deployment_ref.name, len(owned_rs_uids),
    )

    pods = core_api.list_namespaced_pod(deployment_ref.namespace)
    return [
        ObjectRef(
            kind="Pod", namespace=deployment_ref.namespace, name=pod.metadata.name
        )
        for pod in pods.items
        if any(
            ref.uid in owned_rs_uids for ref in (pod.metadata.owner_references or [])
        )
    ]
