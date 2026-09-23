from unittest.mock import MagicMock, patch

from langchain_core.documents import Document

from knowledge_base.retrieve import retrieve_runbooks


@patch("knowledge_base.retrieve.get_vector_store")
def test_retrieve_runbooks_maps_documents_to_chunks(mock_get_vector_store):
    doc = Document(
        id="oom-killed#diagnosis",
        page_content="diagnosis text",
        metadata={
            "failure_class": "OOMKilled",
            "section": "Diagnosis",
            "source_file": "oom-killed.md",
        },
    )
    retriever = MagicMock()
    retriever.invoke.return_value = [doc]
    vector_store = MagicMock()
    vector_store.as_retriever.return_value = retriever
    mock_get_vector_store.return_value = vector_store

    chunks = retrieve_runbooks("OOMKilled", k=3)

    vector_store.as_retriever.assert_called_once_with(search_kwargs={"k": 3})
    retriever.invoke.assert_called_once_with("OOMKilled")
    assert len(chunks) == 1
    assert chunks[0].id == "oom-killed#diagnosis"
    assert chunks[0].failure_class == "OOMKilled"
    assert chunks[0].section == "Diagnosis"
    assert chunks[0].text == "diagnosis text"
    assert chunks[0].source_file == "oom-killed.md"


@patch("knowledge_base.retrieve.get_vector_store")
def test_retrieve_runbooks_empty_results(mock_get_vector_store):
    retriever = MagicMock()
    retriever.invoke.return_value = []
    vector_store = MagicMock()
    vector_store.as_retriever.return_value = retriever
    mock_get_vector_store.return_value = vector_store

    assert retrieve_runbooks("nothing matches", k=3) == []
