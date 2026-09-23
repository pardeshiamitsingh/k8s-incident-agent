"""Deterministic evidence -> failure-class classification (spec 003).

No LLM call: every failure class handled here corresponds to a literal
K8s `reason` string already captured in spec 001's evidence models
(`ContainerState.reason`, `K8sEvent.reason`).

Not every failure class in spec 002's runbook taxonomy is reachable this
way -- `DNSResolutionFailure` and `AppRBACDenied` only ever surface in
*application log content*, not a structured K8s reason field, and
`StuckTerminating` needs `metadata.deletionTimestamp`/`finalizers`, which
spec 001's `ObjectDescribeSnapshot` doesn't currently capture. Evidence for
those three still reaches the Diagnose node in full (raw events/logs); it
just isn't pre-labelled by this classifier. Extending the collector's
model to add deletion/finalizer fields, or adding a log-content signal, is
future work, not a bug in this table.
"""

import logging

from collectors.models import IncidentEvidence

logger = logging.getLogger(__name__)

REASON_TO_FAILURE_CLASS: dict[str, str] = {
    "CrashLoopBackOff": "CrashLoopBackOff",
    "OOMKilled": "OOMKilled",
    "ImagePullBackOff": "ImagePullBackOff",
    "ErrImagePull": "ImagePullBackOff",
    "ErrImageNeverPull": "ErrImageNeverPull",
    "CreateContainerConfigError": "CreateContainerConfigError",
    "FailedScheduling": "Pending",
    "Unhealthy": "ProbeFailure",
    "Evicted": "NodePressureEviction",
    "FailedMount": "PVCBindingFailure",
    "ProvisioningFailed": "PVCBindingFailure",
    "FailedAttachVolume": "PVCBindingFailure",
}

UNKNOWN = "Unknown"


def classify_evidence(evidence: IncidentEvidence) -> list[str]:
    """Returns the sorted, deduped list of failure classes matched anywhere
    in `evidence` (including recursively through `evidence.pods` for a
    Deployment). Returns `["Unknown"]` if nothing in the lookup table
    matched."""
    matched: set[str] = set()
    _classify_single(evidence, matched)
    for pod_evidence in evidence.pods:
        _classify_single(pod_evidence, matched)

    if not matched:
        logger.info(
            "no known reason matched for %s %s/%s, classifying as %s",
            evidence.object_ref.kind, evidence.object_ref.namespace,
            evidence.object_ref.name, UNKNOWN,
        )
        return [UNKNOWN]

    result = sorted(matched)
    logger.info(
        "classified %s %s/%s as %s",
        evidence.object_ref.kind, evidence.object_ref.namespace,
        evidence.object_ref.name, result,
    )
    return result


def _classify_single(evidence: IncidentEvidence, matched: set[str]) -> None:
    """Matches one object's own container-state and event reasons into
    `matched` (in place) -- does not recurse into `evidence.pods` itself,
    so callers control the recursion depth."""
    for container_status in evidence.describe.container_statuses:
        reason = container_status.state.reason
        if reason in REASON_TO_FAILURE_CLASS:
            matched.add(REASON_TO_FAILURE_CLASS[reason])

    for event in evidence.events:
        if event.reason in REASON_TO_FAILURE_CLASS:
            matched.add(REASON_TO_FAILURE_CLASS[event.reason])
