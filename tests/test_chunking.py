from pathlib import Path

import pytest

from knowledge_base.chunking import chunk_id, parse_runbook


def test_parse_runbook_frontmatter_and_sections(tmp_path):
    path = tmp_path / "example.md"
    path.write_text(
        "---\n"
        "id: example\n"
        "failure_class: Example\n"
        "symptoms:\n"
        "  - one\n"
        "  - two\n"
        "---\n"
        "\n"
        "## Diagnosis\n"
        "Do this first.\n"
        "\n"
        "## Remediation\n"
        "Then do this.\n"
    )

    frontmatter, sections = parse_runbook(path)

    assert frontmatter == {
        "id": "example",
        "failure_class": "Example",
        "symptoms": ["one", "two"],
    }
    assert sections == [
        ("Diagnosis", "Do this first."),
        ("Remediation", "Then do this."),
    ]


def test_parse_runbook_missing_frontmatter_raises(tmp_path):
    path = tmp_path / "no-frontmatter.md"
    path.write_text("## Diagnosis\nNo frontmatter here.\n")

    with pytest.raises(ValueError):
        parse_runbook(path)


def test_parse_runbook_no_sections_returns_empty_list(tmp_path):
    path = tmp_path / "empty.md"
    path.write_text("---\nid: x\nfailure_class: X\n---\nJust prose, no headings.\n")

    _, sections = parse_runbook(path)

    assert sections == []


def test_chunk_id_slugifies_section():
    assert chunk_id("oom-killed.md", "Diagnosis") == "oom-killed#diagnosis"
    assert (
        chunk_id("pvc-binding-failure.md", "Some Heading")
        == "pvc-binding-failure#some-heading"
    )
