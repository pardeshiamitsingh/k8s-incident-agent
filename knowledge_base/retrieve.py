"""Runbook retrieval, via LangChain's vector store retriever interface
(spec 002)."""

import logging

from .ingest import get_vector_store
from .models import RunbookChunk

logger = logging.getLogger(__name__)


def retrieve_runbooks(query: str, k: int = 5) -> list[RunbookChunk]:
    vector_store = get_vector_store()
    retriever = vector_store.as_retriever(search_kwargs={"k": k})
    documents = retriever.invoke(query)

    chunks = [
        RunbookChunk(
            id=doc.id,
            failure_class=doc.metadata["failure_class"],
            section=doc.metadata["section"],
            text=doc.page_content,
            source_file=doc.metadata["source_file"],
        )
        for doc in documents
    ]
    logger.info(
        "query=%r returned %d chunk(s): %s",
        query, len(chunks), [c.id for c in chunks],
    )
    return chunks
