"""Container log collection for a single Pod (spec 001).

Previous-container logs are only fetched when a container has actually
restarted -- otherwise the API call would just fail with "previous
terminated container not found".
"""

from kubernetes.client.exceptions import ApiException

from .k8s_client import build_api_client
from .models import LogsSnapshot, ObjectRef


def get_logs(object_ref: ObjectRef) -> dict[str, LogsSnapshot]:
    api = build_api_client()
    pod = api.read_namespaced_pod(object_ref.name, object_ref.namespace)

    logs: dict[str, LogsSnapshot] = {}
    for cs in pod.status.container_statuses or []:
        has_restarted = cs.restart_count > 0 or (
            cs.last_state is not None and cs.last_state.terminated is not None
        )
        logs[cs.name] = LogsSnapshot(
            current=_read_log(api, object_ref, cs.name, previous=False),
            previous=(
                _read_log(api, object_ref, cs.name, previous=True)
                if has_restarted
                else None
            ),
        )
    return logs


def _read_log(api, object_ref: ObjectRef, container_name: str, previous: bool) -> str | None:
    try:
        return api.read_namespaced_pod_log(
            object_ref.name,
            object_ref.namespace,
            container=container_name,
            previous=previous,
        )
    except ApiException:
        return None
