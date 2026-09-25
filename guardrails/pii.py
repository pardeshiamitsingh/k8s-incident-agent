"""Regex PII and secret masking (spec 013).

Dependency-free on purpose. IP addresses, hostnames, namespaces and pod
names are deliberately NOT masked: they are the incident data. Every
pattern is anchored or guarded so timestamps, versions and IPs don't match.
"""

import re

_PEM = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL
)
_URL_CREDENTIALS = re.compile(r"(?<=://)[^/\s:@]+:[^/\s@]+@")
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]*")
_CLOUD_KEY = re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")
_BEARER = re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9\-._~+/]{8,}=*")
_ASSIGNMENT = re.compile(
    r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key)\b"
    r"(\s*[:=]\s*)([\"']?)(?!\[)([^\s\"',;]+)"
)
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\b")
_SSN = re.compile(r"\b(?!000|666|9\d\d)\d{3}-(?!00)\d{2}-(?!0000)\d{4}\b")
# Grouped (4-4-4-4 / 4-6-5) or 15-16 contiguous digits starting 3-6; Luhn-checked.
_CARD = re.compile(
    r"(?<![\d-])(?:\d{4}[ -]\d{4}[ -]\d{4}[ -]\d{1,7}|\d{4}[ -]\d{6}[ -]\d{5}|[3-6]\d{14,15})(?![\d-])"
)
_PHONE = re.compile(
    r"(?<![\w.+-])(?:\+\d{1,3}[ .-]?)?(?:\(\d{3}\)[ .-]?|\d{3}[ .-])\d{3}[ .-]\d{4}(?![\w-])"
    r"|(?<![\w.])\+\d{1,3}[ -]\d{2,4}[ -]\d{3,4}[ -]\d{3,4}(?![\w-])"
)


def _luhn_valid(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def mask(text: str) -> tuple[str, dict[str, int]]:
    """Returns `(masked_text, counts_by_label)`. Idempotent: already-masked
    placeholders are left alone."""
    counts: dict[str, int] = {}

    def bump(label: str) -> None:
        counts[label] = counts.get(label, 0) + 1

    def sub(pattern: re.Pattern, replacement, label: str, text: str) -> str:
        def repl(match: re.Match) -> str:
            bump(label)
            return replacement(match) if callable(replacement) else replacement

        return pattern.sub(repl, text)

    text = sub(_PEM, "[SECRET]", "secret", text)
    text = sub(_URL_CREDENTIALS, "[CREDENTIALS]@", "credentials", text)
    text = sub(_JWT, "[JWT]", "jwt", text)
    text = sub(_CLOUD_KEY, "[SECRET]", "secret", text)
    text = sub(_BEARER, lambda m: f"{m.group(1)} [SECRET]", "secret", text)
    text = sub(
        _ASSIGNMENT,
        lambda m: f"{m.group(1)}{m.group(2)}{m.group(3)}[SECRET]",
        "secret",
        text,
    )
    text = sub(_EMAIL, "[EMAIL]", "email", text)
    text = sub(_SSN, "[SSN]", "ssn", text)

    def card(match: re.Match) -> str:
        digits = re.sub(r"\D", "", match.group(0))
        if 13 <= len(digits) <= 19 and _luhn_valid(digits):
            bump("card")
            return "[CARD]"
        return match.group(0)

    text = _CARD.sub(card, text)
    text = sub(_PHONE, "[PHONE]", "phone", text)
    return text, counts
