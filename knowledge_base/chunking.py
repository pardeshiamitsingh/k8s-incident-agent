"""Runbook markdown parsing: frontmatter + per-`##`-section chunking (spec 002)."""

from pathlib import Path

import yaml


def parse_runbook(path: Path) -> tuple[dict, list[tuple[str, str]]]:
    text = path.read_text()
    if not text.startswith("---"):
        raise ValueError(f"{path} is missing YAML frontmatter")

    _, frontmatter_raw, body = text.split("---", 2)
    frontmatter = yaml.safe_load(frontmatter_raw)
    return frontmatter, _split_sections(body)


def _split_sections(body: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    heading: str | None = None
    lines: list[str] = []

    for line in body.splitlines():
        if line.startswith("## "):
            if heading is not None:
                sections.append((heading, "\n".join(lines).strip()))
            heading = line[3:].strip()
            lines = []
        else:
            lines.append(line)

    if heading is not None:
        sections.append((heading, "\n".join(lines).strip()))

    return sections


def chunk_id(source_file: str, section: str) -> str:
    slug = section.lower().replace(" ", "-")
    return f"{Path(source_file).stem}#{slug}"
