"""Data shapes for the runbook knowledge base (spec 002)."""

from pydantic import BaseModel


class RunbookChunk(BaseModel):
    id: str
    failure_class: str
    section: str
    text: str
    source_file: str
