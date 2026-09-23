"""Renders evidence and runbook chunks into prompt text for the LLM nodes
(spec 003)."""

from collectors.models import IncidentEvidence
from knowledge_base.models import RunbookChunk

LOG_TAIL_CHARS = 1500


def format_evidence(evidence: IncidentEvidence, indent: str = "") -> str:
    """Renders one object's evidence (phase, conditions, container states,
    events, tailed logs) as plain text, recursing into `evidence.pods`
    with increasing indent for a Deployment's owned pods."""
    ref = evidence.object_ref
    lines = [f"{indent}Object: {ref.kind} {ref.namespace}/{ref.name}"]
    lines.append(f"{indent}Phase: {evidence.describe.phase}")

    for condition in evidence.describe.conditions:
        lines.append(
            f"{indent}Condition: {condition.type}={condition.status}"
            f" reason={condition.reason} message={condition.message}"
        )

    for container_status in evidence.describe.container_statuses:
        state = container_status.state
        lines.append(
            f"{indent}Container {container_status.name}: state={state.phase}"
            f" reason={state.reason} message={state.message}"
            f" restart_count={container_status.restart_count}"
            f" requests={container_status.resource_requests}"
            f" limits={container_status.resource_limits}"
        )

    for event in evidence.events:
        lines.append(
            f"{indent}Event: reason={event.reason} type={event.type}"
            f" count={event.count} message={event.message}"
        )

    for container_name, logs in evidence.logs.items():
        if logs.current:
            lines.append(
                f"{indent}Logs[{container_name}].current (tail): "
                f"{logs.current[-LOG_TAIL_CHARS:]}"
            )
        if logs.previous:
            lines.append(
                f"{indent}Logs[{container_name}].previous (tail): "
                f"{logs.previous[-LOG_TAIL_CHARS:]}"
            )

    for pod_evidence in evidence.pods:
        lines.append(f"{indent}--- owned pod ---")
        lines.append(format_evidence(pod_evidence, indent=indent + "  "))

    return "\n".join(lines)


def format_chunks(chunks: list[RunbookChunk]) -> str:
    """Renders retrieved runbook chunks as plain text, each prefixed with
    its `[chunk_id]` so the LLM can cite that exact ID back."""
    return "\n\n".join(
        f"[{chunk.id}] ({chunk.failure_class} / {chunk.section})\n{chunk.text}"
        for chunk in chunks
    )
