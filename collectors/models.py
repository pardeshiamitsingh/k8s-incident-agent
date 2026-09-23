"""Pydantic data shapes for collected K8s evidence (spec 001)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

ObjectKind = Literal["Pod", "Deployment"]


class ObjectRef(BaseModel):
    kind: ObjectKind
    namespace: str
    name: str


class K8sEvent(BaseModel):
    reason: str
    message: str
    type: str
    count: int
    first_seen: datetime
    last_seen: datetime
    source_component: str | None = None


class ContainerState(BaseModel):
    phase: Literal["waiting", "running", "terminated"]
    reason: str | None = None
    message: str | None = None


class ContainerStatus(BaseModel):
    name: str
    state: ContainerState
    restart_count: int
    image: str
    resource_requests: dict[str, str] = {}
    resource_limits: dict[str, str] = {}


class OwnerReference(BaseModel):
    kind: str
    name: str
    uid: str
    controller: bool = False


class ObjectCondition(BaseModel):
    type: str
    status: str
    reason: str | None = None
    message: str | None = None


class ObjectDescribeSnapshot(BaseModel):
    phase: str
    conditions: list[ObjectCondition] = []
    container_statuses: list[ContainerStatus] = []
    owner_references: list[OwnerReference] = []


class LogsSnapshot(BaseModel):
    current: str | None = None
    previous: str | None = None


class IncidentEvidence(BaseModel):
    object_ref: ObjectRef
    collected_at: datetime
    events: list[K8sEvent]
    describe: ObjectDescribeSnapshot
    logs: dict[str, LogsSnapshot]
    pods: list["IncidentEvidence"] = []


IncidentEvidence.model_rebuild()
