"""Unicode normalisation and length limits (spec 013)."""

import re
import unicodedata

QUERY_MAX_CHARS = 2000
NOTES_MAX_CHARS = 2000
POSTMORTEM_MAX_CHARS = 4000

_WHITESPACE_RUN = re.compile(r"[ \t]+")
_LINE_EDGE_SPACE = re.compile(r" *\n *")
_BLANK_LINES = re.compile(r"\n{3,}")


def normalize(text: str) -> str:
    """NFKC-fold (defeats full-width and compatibility-character
    obfuscation), drop zero-width/format characters, turn other control
    characters into spaces, and collapse runs of whitespace."""
    text = unicodedata.normalize("NFKC", text)
    cleaned: list[str] = []
    for ch in text:
        category = unicodedata.category(ch)
        if category == "Cf":
            continue
        if category == "Cc" and ch not in "\n\t":
            cleaned.append(" ")
        else:
            cleaned.append(ch)
    text = "".join(cleaned)
    text = _WHITESPACE_RUN.sub(" ", text)
    text = _LINE_EDGE_SPACE.sub("\n", text)
    text = _BLANK_LINES.sub("\n\n", text)
    return text.strip()
