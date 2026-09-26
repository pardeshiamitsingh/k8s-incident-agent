"""Runbook retrieval, via LangChain retrievers (spec 002, spec 014).

Two modes, chosen by `INCIDENT_AGENT_RETRIEVAL_MODE`:
- `dense` (default until spec 014's evaluation gate passes): today's
  vector-similarity retrieval, unchanged.
- `hybrid`: dense + BM25 candidates fused by reciprocal-rank fusion, then
  reranked by a local FlashRank cross-encoder.
"""

import logging
import os
import re
from functools import lru_cache
from pathlib import Path

from langchain_classic.retrievers import EnsembleRetriever
from langchain_community.document_compressors.flashrank_rerank import FlashrankRerank
from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document

from .ingest import get_vector_store
from .models import RunbookChunk

logger = logging.getLogger(__name__)

MODE_ENV_VAR = "INCIDENT_AGENT_RETRIEVAL_MODE"
DEFAULT_MODE = "dense"
CANDIDATES = 10

RERANK_MODEL_ENV_VAR = "INCIDENT_AGENT_RERANK_MODEL"
DEFAULT_RERANK_MODEL = "ms-marco-MiniLM-L-12-v2"
DEFAULT_RERANK_CACHE = Path(__file__).parent.parent / ".cache" / "flashrank"


def retrieval_mode() -> str:
    mode = os.environ.get(MODE_ENV_VAR, DEFAULT_MODE).lower()
    if mode not in ("dense", "hybrid"):
        logger.warning("unknown %s=%r, using %r", MODE_ENV_VAR, mode, DEFAULT_MODE)
        return DEFAULT_MODE
    return mode


def rerank_model_name() -> str:
    return os.environ.get(RERANK_MODEL_ENV_VAR, DEFAULT_RERANK_MODEL)


def rerank_cache_dir() -> Path:
    return Path(os.environ.get("INCIDENT_AGENT_RERANK_CACHE", DEFAULT_RERANK_CACHE))


@lru_cache(maxsize=1)
def _reranker_client():
    """One FlashRank `Ranker` per process (loading the model is the only
    expensive step). Returns None if the model isn't already on disk: the
    runtime never downloads anything, `fetch_reranker` does that once at
    setup."""
    from flashrank import Ranker

    model_dir = rerank_cache_dir() / rerank_model_name()
    if not model_dir.exists():
        logger.warning(
            "reranker model %s not found at %s; run `python -m "
            "knowledge_base.fetch_reranker`. Returning unreranked hybrid order.",
            rerank_model_name(), model_dir,
        )
        return None
    return Ranker(model_name=rerank_model_name(), cache_dir=str(rerank_cache_dir()))


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _dense_documents(query: str, k: int) -> list[Document]:
    retriever = get_vector_store().as_retriever(search_kwargs={"k": k})
    return retriever.invoke(query)


def _hybrid_documents(query: str, k: int) -> list[Document]:
    vector_store = get_vector_store()

    # Rebuilt from the collection on every call: ~50 chunks, so it costs
    # milliseconds, and it can never be stale relative to a postmortem another
    # process just wrote (spec 004 / spec 009's cross-process staleness).
    stored = vector_store.get()
    corpus = [
        Document(id=doc_id, page_content=text, metadata=meta)
        for doc_id, text, meta in zip(stored["ids"], stored["documents"], stored["metadatas"])
    ]
    if not corpus:
        return []

    bm25 = BM25Retriever.from_documents(corpus, k=CANDIDATES, preprocess_func=_tokens)
    dense = vector_store.as_retriever(search_kwargs={"k": CANDIDATES})
    fused = EnsembleRetriever(retrievers=[bm25, dense], weights=[0.5, 0.5]).invoke(query)

    client = _reranker_client()
    if client is None:
        return fused[:k]

    reranked = FlashrankRerank(client=client, top_n=k).compress_documents(fused, query)
    # FlashrankRerank rebuilds documents without `id`; its metadata "id" is the
    # index into `fused`, which recovers the original document (and its id).
    documents = []
    for doc in reranked:
        original = fused[doc.metadata["id"]]
        logger.debug("rerank %s score=%.4f", original.id, doc.metadata["relevance_score"])
        documents.append(original)
    return documents


def retrieve_runbooks(query: str, k: int = 5) -> list[RunbookChunk]:
    mode = retrieval_mode()
    documents = _hybrid_documents(query, k) if mode == "hybrid" else _dense_documents(query, k)

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
        "mode=%s query=%r returned %d chunk(s): %s",
        mode, query[:120], len(chunks), [c.id for c in chunks],
    )
    return chunks
