"""Rejection audit trail (spec 013, constitution principle 5). Never logs
raw input: only endpoint, reason, pattern name, length and a hash prefix."""

import hashlib
import logging

logger = logging.getLogger("guardrails.audit")


def log_rejection(
    endpoint: str, reason: str, text: str, pattern: str | None = None
) -> None:
    digest = hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:12]
    logger.warning(
        "guardrail rejection endpoint=%s reason=%s pattern=%s length=%d sha256=%s",
        endpoint, reason, pattern or "-", len(text), digest,
    )


def log_redactions(endpoint: str, redactions: dict[str, int]) -> None:
    if redactions:
        logger.info("guardrail redactions endpoint=%s counts=%s", endpoint, redactions)
