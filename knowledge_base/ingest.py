"""Runbook ingestion into Chroma, via LangChain's vector store wrapper
(spec 002).

Re-running this after editing a runbook is safe: chunks are deleted and
re-added per source file, so a renamed or removed section doesn't leave a
stale chunk behind in the collection.
"""

import logging
import os
from pathlib import Path

from langchain_chroma import Chroma
from langchain_core.documents import Document

from .chunking import chunk_id, parse_runbook
from .embeddings import get_embeddings
from .models import RunbookChunk

logger = logging.getLogger(__name__)

RUNBOOKS_DIR = Path(__file__).parent / "runbooks"
DEFAULT_CHROMA_PATH = Path(__file__).parent.parent / ".chroma"
COLLECTION_NAME = "runbooks"


def chroma_path() -> Path:
    return Path(os.environ.get("INCIDENT_AGENT_CHROMA_PATH", DEFAULT_CHROMA_PATH))


def get_vector_store() -> Chroma:
    """Server mode (spec 009) when `INCIDENT_AGENT_CHROMA_HOST` is set --
    required once more than one process touches the store concurrently
    (multiple RQ workers), since an embedded `PersistentClient` isn't safe
    for that (spec 004's cross-process consistency bug). Falls back to
    today's embedded single-process mode otherwise, so local dev and the
    existing test suite are unaffected."""
    host = os.environ.get("INCIDENT_AGENT_CHROMA_HOST")
    if host:
        port = int(os.environ.get("INCIDENT_AGENT_CHROMA_PORT", "8000"))
        logger.debug("using Chroma server mode at %s:%d", host, port)
        return Chroma(
            collection_name=COLLECTION_NAME,
            embedding_function=get_embeddings(),
            host=host,
            port=port,
        )

    return Chroma(
        collection_name=COLLECTION_NAME,
        embedding_function=get_embeddings(),
        persist_directory=str(chroma_path()),
    )


def _chunks_for_file(path: Path) -> list[RunbookChunk]:
    frontmatter, sections = parse_runbook(path)
    failure_class = frontmatter["failure_class"]
    return [
        RunbookChunk(
            id=chunk_id(path.name, section),
            failure_class=failure_class,
            section=section,
            text=text,
            source_file=path.name,
        )
        for section, text in sections
    ]


def ingest_runbooks(runbooks_dir: Path = RUNBOOKS_DIR) -> int:
    vector_store = get_vector_store()
    total = 0

    for path in sorted(runbooks_dir.glob("*.md")):
        chunks = _chunks_for_file(path)
        if not chunks:
            logger.warning("no '##' sections found in %s, skipping", path.name)
            continue

        existing = vector_store.get(where={"source_file": path.name})
        if existing["ids"]:
            vector_store.delete(ids=existing["ids"])

        vector_store.add_documents(
            [
                Document(
                    page_content=c.text,
                    metadata={
                        "failure_class": c.failure_class,
                        "section": c.section,
                        "source_file": c.source_file,
                    },
                )
                for c in chunks
            ],
            ids=[c.id for c in chunks],
        )
        logger.debug("ingested %d chunk(s) from %s", len(chunks), path.name)
        total += len(chunks)

    logger.info(
        "ingested %d total chunk(s) into collection '%s' at %s",
        total, COLLECTION_NAME, chroma_path(),
    )
    return total
