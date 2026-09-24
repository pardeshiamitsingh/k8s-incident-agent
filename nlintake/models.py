"""Data shapes for natural-language intake (spec 008).

`MentionResult` (the API response shape combining a resolution outcome
with a job_id) lives in `api/schemas.py` instead -- same split as
`Job`/`JobStatus`: this module owns resolution, the API layer owns what a
caller sees.
"""

from pydantic import BaseModel

from collectors.models import ObjectRef


class DetectedMention(BaseModel):
    mentioned_service: str
    notes: str | None = None


class DetectedMentions(BaseModel):
    """Wraps the list for structured-output binding -- LangChain's
    structured-output binding needs a top-level object, not a bare list
    (a bare `list[Model]` schema fails at invoke time, verified directly
    against ChatOllama before choosing this shape)."""

    mentions: list[DetectedMention]


class AmbiguousMatch(BaseModel):
    """`resolve_mention()`'s result when multiple Deployments match and
    health doesn't disambiguate -- never a silent pick."""

    candidates: list[ObjectRef]


class NotFound(BaseModel):
    """`resolve_mention()`'s result when nothing matches."""
