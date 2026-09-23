from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from kubernetes.client import CoreV1Event, CoreV1EventList, V1EventSource, V1ObjectMeta

from collectors.events import get_events
from collectors.models import ObjectRef


def _event(**overrides) -> CoreV1Event:
    defaults = dict(
        metadata=V1ObjectMeta(),
        reason="Failed",
        message="pull failed",
        type="Warning",
        count=3,
        first_timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        last_timestamp=datetime(2026, 1, 1, 0, 5, tzinfo=timezone.utc),
        source=V1EventSource(component="kubelet"),
    )
    defaults.update(overrides)
    return CoreV1Event(**defaults)


@patch("collectors.events.build_api_client")
def test_get_events_maps_fields(mock_build_client):
    api = MagicMock()
    api.list_namespaced_event.return_value = CoreV1EventList(items=[_event()])
    mock_build_client.return_value = api

    ref = ObjectRef(kind="Pod", namespace="ns", name="my-pod")
    events = get_events(ref)

    assert len(events) == 1
    event = events[0]
    assert event.reason == "Failed"
    assert event.message == "pull failed"
    assert event.type == "Warning"
    assert event.count == 3
    assert event.source_component == "kubelet"

    api.list_namespaced_event.assert_called_once_with(
        "ns", field_selector="involvedObject.name=my-pod,involvedObject.kind=Pod"
    )


@patch("collectors.events.build_api_client")
def test_get_events_defaults_count_and_missing_source(mock_build_client):
    api = MagicMock()
    api.list_namespaced_event.return_value = CoreV1EventList(
        items=[_event(count=None, source=None)]
    )
    mock_build_client.return_value = api

    ref = ObjectRef(kind="Deployment", namespace="ns", name="my-deploy")
    events = get_events(ref)

    assert events[0].count == 1
    assert events[0].source_component is None


@patch("collectors.events.build_api_client")
def test_get_events_empty(mock_build_client):
    api = MagicMock()
    api.list_namespaced_event.return_value = CoreV1EventList(items=[])
    mock_build_client.return_value = api

    ref = ObjectRef(kind="Pod", namespace="ns", name="my-pod")
    assert get_events(ref) == []
