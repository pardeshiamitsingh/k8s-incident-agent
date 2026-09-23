"""Data shapes for incident intake resolution (spec 005)."""

from typing import Literal

from pydantic import BaseModel


class IntakeRequest(BaseModel):
    namespace: str
    name: str
    kind: Literal["Pod", "Deployment"] | None = None
    notes: str | None = None


class ResolutionError(BaseModel):
    """Why `resolve_intake()` couldn't produce an `ObjectRef`.

    `reason` distinguishes the two cases spec 007's HTTP handler maps to
    different status codes: `not_found` -> 404, `ambiguous` -> 409.
    """

    reason: Literal["not_found", "ambiguous"]
    message: str
