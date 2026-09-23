from unittest.mock import MagicMock, patch

from knowledge_base.ingest import ingest_runbooks


def _write_runbook(dir_path, filename, failure_class, sections):
    body = "".join(f"## {heading}\n{text}\n\n" for heading, text in sections)
    (dir_path / filename).write_text(
        f"---\nid: {filename}\nfailure_class: {failure_class}\n---\n\n{body}"
    )


@patch("knowledge_base.ingest.get_vector_store")
def test_ingest_runbooks_adds_chunks_per_file(mock_get_vector_store, tmp_path):
    _write_runbook(
        tmp_path, "a.md", "FailureA", [("Diagnosis", "diag a"), ("Remediation", "fix a")]
    )
    _write_runbook(tmp_path, "b.md", "FailureB", [("Diagnosis", "diag b")])

    vector_store = MagicMock()
    vector_store.get.return_value = {"ids": []}
    mock_get_vector_store.return_value = vector_store

    total = ingest_runbooks(runbooks_dir=tmp_path)

    assert total == 3
    assert vector_store.add_documents.call_count == 2

    first_call_docs, first_call_kwargs = vector_store.add_documents.call_args_list[0]
    assert first_call_kwargs["ids"] == ["a#diagnosis", "a#remediation"]
    assert [d.page_content for d in first_call_docs[0]] == ["diag a", "fix a"]
    assert first_call_docs[0][0].metadata == {
        "failure_class": "FailureA",
        "section": "Diagnosis",
        "source_file": "a.md",
    }


@patch("knowledge_base.ingest.get_vector_store")
def test_ingest_runbooks_deletes_stale_chunks_before_readding(
    mock_get_vector_store, tmp_path
):
    _write_runbook(tmp_path, "a.md", "FailureA", [("Diagnosis", "diag a")])

    vector_store = MagicMock()
    vector_store.get.return_value = {"ids": ["a#diagnosis", "a#old-stale-section"]}
    mock_get_vector_store.return_value = vector_store

    ingest_runbooks(runbooks_dir=tmp_path)

    vector_store.delete.assert_called_once_with(
        ids=["a#diagnosis", "a#old-stale-section"]
    )


@patch("knowledge_base.ingest.get_vector_store")
def test_ingest_runbooks_skips_file_with_no_sections(mock_get_vector_store, tmp_path):
    (tmp_path / "empty.md").write_text(
        "---\nid: empty\nfailure_class: Empty\n---\nNo headings here.\n"
    )

    vector_store = MagicMock()
    mock_get_vector_store.return_value = vector_store

    total = ingest_runbooks(runbooks_dir=tmp_path)

    assert total == 0
    vector_store.add_documents.assert_not_called()
