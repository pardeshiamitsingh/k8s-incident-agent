"""Live smoke tests for the knowledge_base ingestion/retrieval pipeline.

Requires a local Ollama server with nomic-embed-text pulled (spec 002) --
not run by default:

    uv run pytest -m requires_ollama tests/integration/
"""

import os

import pytest

from knowledge_base.chunking import parse_runbook
from knowledge_base.ingest import RUNBOOKS_DIR, get_vector_store, ingest_runbooks
from knowledge_base.retrieve import retrieve_runbooks

pytestmark = pytest.mark.requires_ollama

# One per representative query, mirroring verify_retrieval.py -- but here
# each expectation is an assertion, not just something to eyeball.
RETRIEVAL_CASES = [
    ("OOMKilled", "OOMKilled"),
    ("container image cannot be pulled", "ImagePullBackOff"),
    ("pod stuck pending and never scheduled", "Pending"),
    ("DNS lookups failing inside the pod", "DNSResolutionFailure"),
    ("pod stuck terminating forever", "StuckTerminating"),
    (
        "missing ConfigMap causing container to never start",
        "CreateContainerConfigError",
    ),
    ("readiness probe failing, pod not receiving traffic", "ProbeFailure"),
]


def _expected_chunk_count() -> int:
    total = 0
    for path in RUNBOOKS_DIR.glob("*.md"):
        _, sections = parse_runbook(path)
        total += len(sections)
    return total


@pytest.fixture(scope="module")
def ingested_chunk_count(tmp_path_factory):
    """Ingests the real runbooks into an isolated, module-scoped Chroma
    store once, and leaves the dev '.chroma/' directory untouched."""
    path = tmp_path_factory.mktemp("chroma")
    previous = os.environ.get("INCIDENT_AGENT_CHROMA_PATH")
    os.environ["INCIDENT_AGENT_CHROMA_PATH"] = str(path)
    try:
        yield ingest_runbooks()
    finally:
        if previous is None:
            os.environ.pop("INCIDENT_AGENT_CHROMA_PATH", None)
        else:
            os.environ["INCIDENT_AGENT_CHROMA_PATH"] = previous


def test_ingest_runbooks_populates_expected_chunk_count(ingested_chunk_count):
    assert ingested_chunk_count > 0
    assert ingested_chunk_count == _expected_chunk_count()


@pytest.mark.parametrize("query,expected_failure_class", RETRIEVAL_CASES)
def test_retrieve_runbooks_top_hit_matches_failure_class(
    query, expected_failure_class, ingested_chunk_count
):
    top = retrieve_runbooks(query, k=3)[0]
    assert top.failure_class == expected_failure_class


def test_reingestion_replaces_stale_chunks(tmp_path, monkeypatch):
    monkeypatch.setenv("INCIDENT_AGENT_CHROMA_PATH", str(tmp_path / ".chroma"))
    runbook = tmp_path / "temp-runbook.md"

    runbook.write_text(
        "---\nid: temp\nfailure_class: Temp\n---\n\n## OldHeading\noriginal text\n"
    )
    ingest_runbooks(runbooks_dir=tmp_path)
    vector_store = get_vector_store()
    assert "temp-runbook#oldheading" in vector_store.get()["ids"]

    runbook.write_text(
        "---\nid: temp\nfailure_class: Temp\n---\n\n## NewHeading\nupdated text\n"
    )
    ingest_runbooks(runbooks_dir=tmp_path)

    ids = get_vector_store().get()["ids"]
    assert "temp-runbook#newheading" in ids
    assert "temp-runbook#oldheading" not in ids
