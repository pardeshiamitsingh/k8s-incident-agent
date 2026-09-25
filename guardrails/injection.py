"""Prompt-injection pattern matching (spec 013).

Runs on normalised text, case-folded, with light leetspeak folding, plus a
"squashed" check (all non-alphanumerics removed) to catch spaced-out or
punctuated phrasing like "i.g.n.o.r.e previous instructions".

Patterns are deliberately specific: benign incident text such as "ignore
the failing probe" or "context deadline exceeded" must not match, because
the same patterns also run over log lines (`for_evidence=True`), where a
false positive hides real evidence.
"""

import re

_LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s"})

# (name, regex, applies_to_evidence)
_PATTERNS: list[tuple[str, re.Pattern, bool]] = [
    (
        "instruction_override",
        re.compile(
            r"\b(ignore|disregard|forget|override|bypass)\b[^.\n]{0,40}"
            r"\b(previous|prior|above|earlier|preceding|all|any|your|the|these|those)\b[^.\n]{0,30}"
            r"\b(instructions?|prompts?|rules|guidelines|directions|directives)\b"
        ),
        True,
    ),
    (
        "role_reassignment",
        re.compile(
            r"\byou are now\b|\bpretend (you are|to be)\b|\b(act|behave|respond) as (an? )?"
            r"(unrestricted|jailbroken|developer|dan|evil|different|new)\b"
            r"|\bdo anything now\b|\bdan mode\b|\bdeveloper mode\b|\bjailbreak(ed)?\b"
        ),
        True,
    ),
    (
        "system_prompt_probe",
        re.compile(
            r"\b(reveal|show|print|repeat|output|display|leak|tell me|what (is|are))\b[^.\n]{0,40}"
            r"\b(system prompt|(your|the) (initial |original |hidden |system )?(prompt|instructions))\b"
        ),
        True,
    ),
    (
        "template_token",
        re.compile(
            r"<\|[^|>]{1,40}\|>|\[/?inst\]|<</?sys>>|^\s*#{2,}\s*(system|instruction|assistant)\b",
            re.MULTILINE,
        ),
        True,
    ),
    (
        "exfiltrate_or_execute",
        re.compile(
            r"\b(curl|wget)\b[^\n]{0,80}\|\s*(sh|bash)\b"
            r"|\b(send|post|upload|exfiltrate|forward)\b[^.\n]{0,40}\bto\s+https?://"
        ),
        True,
    ),
    ("encoded_blob", re.compile(r"[a-z0-9+/]{200,}={0,2}", re.IGNORECASE), False),
]

_SQUASHED_PHRASES = [
    "ignorepreviousinstructions",
    "ignoreallpreviousinstructions",
    "ignoretheaboveinstructions",
    "disregardpreviousinstructions",
    "disregardallpreviousinstructions",
    "forgetpreviousinstructions",
    "forgetallpreviousinstructions",
    "ignoreyourinstructions",
    "revealyoursystemprompt",
    "youarenowdan",
]


def _fold(text: str) -> str:
    return text.lower().translate(_LEET)


def find_injection(text: str, for_evidence: bool = False) -> str | None:
    """Returns the name of the first matching pattern, or None."""
    folded = _fold(text)
    for name, pattern, applies_to_evidence in _PATTERNS:
        if for_evidence and not applies_to_evidence:
            continue
        # encoded_blob must see the original casing/characters, not leet-folded text
        haystack = text if name == "encoded_blob" else folded
        if pattern.search(haystack):
            return name
    squashed = re.sub(r"[^a-z0-9]", "", folded)
    for phrase in _SQUASHED_PHRASES:
        if phrase in squashed:
            return "instruction_override"
    return None
