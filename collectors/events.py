"""Recent event collection for a single object (spec 001)."""

import logging

from .k8s_client import build_api_client
from .models import K8sEvent, ObjectRef

logger = logging.getLogger(__name__)


def get_events(object_ref: ObjectRef) -> list[K8sEvent]:
    api = build_api_client()
    field_selector = (
        f"involvedObject.name={object_ref.name},"
        f"involvedObject.kind={object_ref.kind}"
    )
    events = api.list_namespaced_event(
        object_ref.namespace, field_selector=field_selector
    )
    logger.debug(
        "found %d event(s) for %s/%s (%s)",
        len(events.items), object_ref.namespace, object_ref.name, object_ref.kind,
    )
    return [
        K8sEvent(
            reason=event.reason,
            message=event.message,
            type=event.type,
            count=event.count or 1,
            first_seen=(
                event.first_timestamp
                or event.event_time
                or event.metadata.creation_timestamp
            ),
            last_seen=(
                event.last_timestamp
                or event.event_time
                or event.metadata.creation_timestamp
            ),
            source_component=event.source.component if event.source else None,
        )
        for event in events.items
    ]
