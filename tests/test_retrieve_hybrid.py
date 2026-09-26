"""Spec 014: hybrid retrieval, with fake stores (no Ollama, no model files)."""

from unittest.mock import MagicMock, patch

import pytest
from langchain_core.documents import Document
from langchain_core.runnables import RunnableLambda

from knowledge_base import retrieve
from knowledge_base.retrieve import retrieval_mode, retrieve_runbooks

CORPUS = {
    "ids": ["oom-killed#diagnosis", "crash-loop-backoff#diagnosis", "ecommerce-orders-db-auth#diagnosis"],
    "documents": [
        "container terminated OOMKilled exit code 137 memory limit",
        "container restarts repeatedly back-off CrashLoopBackOff",
        "orders cannot authenticate to postgres: password authentication failed",
    ],
    "metadatas": [
        {"failure_class": "OOMKilled", "section": "Diagnosis", "source_file": "oom-killed.md"},
        {"failure_class": "CrashLoopBackOff", "section": "Diagnosis", "source_file": "crash-loop-backoff.md"},
        {"failure_class": "CrashLoopBackOff", "section": "Diagnosis", "source_file": "ecommerce-orders-db-auth.md"},
    ],
}


def _fake_store(corpus=CORPUS, dense_ids=("crash-loop-backoff#diagnosis",)):
    store = MagicMock()
    store.get.return_value = corpus
    by_id = {i: (t, m) for i, t, m in zip(corpus["ids"], corpus["documents"], corpus["metadatas"])}
    dense_docs = [Document(id=i, page_content=by_id[i][0], metadata=by_id[i][1]) for i in dense_ids if i in by_id]
    store.as_retriever.return_value = RunnableLambda(lambda _query: dense_docs)
    return store


@pytest.fixture(autouse=True)
def _hybrid_mode(monkeypatch):
    monkeypatch.setenv("INCIDENT_AGENT_RETRIEVAL_MODE", "hybrid")


def test_mode_defaults_to_dense_and_rejects_unknown(monkeypatch):
    monkeypatch.delenv("INCIDENT_AGENT_RETRIEVAL_MODE")
    assert retrieval_mode() == "dense"
    monkeypatch.setenv("INCIDENT_AGENT_RETRIEVAL_MODE", "nonsense")
    assert retrieval_mode() == "dense"


@patch("knowledge_base.retrieve._reranker_client", return_value=None)
@patch("knowledge_base.retrieve.get_vector_store")
def test_bm25_lifts_a_lexical_match_the_dense_side_missed(mock_store, _client):
    mock_store.return_value = _fake_store(dense_ids=("crash-loop-backoff#diagnosis",))

    chunks = retrieve_runbooks("password authentication failed postgres", k=3)

    ids = [c.id for c in chunks]
    assert "ecommerce-orders-db-auth#diagnosis" in ids
    assert ids.index("ecommerce-orders-db-auth#diagnosis") < 2  # RRF ties rank-1 hits from both sides


@patch("knowledge_base.retrieve._reranker_client", return_value=None)
@patch("knowledge_base.retrieve.get_vector_store")
def test_chunk_fields_and_ids_survive_the_round_trip(mock_store, _client):
    mock_store.return_value = _fake_store()

    chunk = next(c for c in retrieve_runbooks("OOMKilled memory limit", k=3) if c.id == "oom-killed#diagnosis")

    assert chunk.id == "oom-killed#diagnosis"
    assert chunk.failure_class == "OOMKilled"
    assert chunk.source_file == "oom-killed.md"
    assert chunk.section == "Diagnosis"


@patch("knowledge_base.retrieve.get_vector_store")
def test_reranker_reorders_and_keeps_original_ids(mock_store):
    mock_store.return_value = _fake_store(dense_ids=("crash-loop-backoff#diagnosis",))
    from flashrank import Ranker

    class FakeRanker(Ranker):
        calls = 0

        def __init__(self):  # no model load
            pass

        def rerank(self, req):
            FakeRanker.calls += 1
            # score by position, reversed, so the order differs from the fused order
            return [
                {"id": p["id"], "text": p["text"], "meta": p["meta"], "score": float(i)}
                for i, p in enumerate(req.passages)
            ][::-1]

    client = FakeRanker()

    with patch("knowledge_base.retrieve._reranker_client", return_value=client):
        chunks = retrieve_runbooks("orders crashing", k=2)

    assert len(chunks) == 2
    assert all(c.id and "#" in c.id for c in chunks)  # ids intact, not the passage index
    assert FakeRanker.calls == 1


@patch("knowledge_base.retrieve._reranker_client", return_value=None)
@patch("knowledge_base.retrieve.get_vector_store")
def test_index_is_rebuilt_from_the_collection_on_every_call(mock_store, _client):
    store = _fake_store()
    mock_store.return_value = store
    retrieve_runbooks("orders", k=3)

    store.get.return_value = {
        "ids": CORPUS["ids"] + ["postmortem-j1-OOMKilled"],
        "documents": CORPUS["documents"] + ["postmortem quokka-marker orders fix"],
        "metadatas": CORPUS["metadatas"] + [
            {"failure_class": "OOMKilled", "section": "Postmortem", "source_file": "postmortem-j1-OOMKilled"}
        ],
    }
    chunks = retrieve_runbooks("quokka-marker", k=3)

    assert "postmortem-j1-OOMKilled" in [c.id for c in chunks]


@patch("knowledge_base.retrieve.get_vector_store")
def test_empty_corpus_returns_nothing(mock_store):
    store = _fake_store({"ids": [], "documents": [], "metadatas": []})
    mock_store.return_value = store
    assert retrieve_runbooks("anything", k=3) == []


def test_missing_reranker_model_degrades_with_a_warning(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("INCIDENT_AGENT_RERANK_CACHE", str(tmp_path))
    retrieve._reranker_client.cache_clear()
    with caplog.at_level("WARNING"):
        assert retrieve._reranker_client() is None
    assert "fetch_reranker" in caplog.text
    retrieve._reranker_client.cache_clear()
