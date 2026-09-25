"""Evidence redaction (spec 013): PII/secret masking and injection
neutralisation on collected free text, before it reaches the LLM prompt,
the job store or the UI.

Only free-text fields are touched (log lines, event and container-state
messages, condition messages). Structured fields the classifier reads
(`reason`, `phase`, restart counts) are never altered, so classification
is unchanged.
"""

import logging

from collectors.models import (
    ContainerState,
    ContainerStatus,
    IncidentEvidence,
    K8sEvent,
    LogsSnapshot,
    ObjectCondition,
)

from . import audit
from .injection import find_injection
from .pii import mask

logger = logging.getLogger(__name__)

NEUTRALISED_LINE = "[REDACTED: possible instruction in log]"


def _clean(text: str | None, counts: dict[str, int]) -> str | None:
    if not text:
        return text
    masked, found = mask(text)
    for label, n in found.items():
        counts[label] = counts.get(label, 0) + n
    lines = masked.split("\n")
    out = []
    for line in lines:
        pattern = find_injection(line, for_evidence=True)
        if pattern:
            counts["injection_line"] = counts.get("injection_line", 0) + 1
            out.append(NEUTRALISED_LINE)
        else:
            out.append(line)
    return "\n".join(out)


def _redact(evidence: IncidentEvidence, counts: dict[str, int]) -> IncidentEvidence:
    events = [
        K8sEvent(**{**e.model_dump(), "message": _clean(e.message, counts)})
        for e in evidence.events
    ]
    conditions = [
        ObjectCondition(**{**c.model_dump(), "message": _clean(c.message, counts)})
        for c in evidence.describe.conditions
    ]
    container_statuses = [
        ContainerStatus(
            **{
                **cs.model_dump(),
                "state": ContainerState(
                    **{**cs.state.model_dump(), "message": _clean(cs.state.message, counts)}
                ),
            }
        )
        for cs in evidence.describe.container_statuses
    ]
    logs = {
        name: LogsSnapshot(
            current=_clean(snapshot.current, counts),
            previous=_clean(snapshot.previous, counts),
        )
        for name, snapshot in evidence.logs.items()
    }
    return evidence.model_copy(
        update={
            "events": events,
            "describe": evidence.describe.model_copy(
                update={"conditions": conditions, "container_statuses": container_statuses}
            ),
            "logs": logs,
            "pods": [_redact(pod, counts) for pod in evidence.pods],
        }
    )


def redact_evidence(evidence: IncidentEvidence) -> IncidentEvidence:
    counts: dict[str, int] = {}
    redacted = _redact(evidence, counts)
    audit.log_redactions(
        f"evidence:{evidence.object_ref.kind}/{evidence.object_ref.name}", counts
    )
    return redacted
