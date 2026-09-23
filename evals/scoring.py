"""Deterministic scoring (spec 006)."""

from agent.state import AgentState

from .models import GoldenCase


def classification_correct(case: GoldenCase, state: AgentState) -> bool:
    """Exact-set match between the classifier's output and the case's
    expected failure classes -- no partial credit, since a wrong or
    missing classification changes which runbooks get retrieved."""
    return set(state.classified_failure_classes) == set(case.expected_failure_classes)


def keyword_hit_rate(text: str, keywords: list[str]) -> float:
    """Fraction of `keywords` found as a case-insensitive substring of
    `text`. Returns 1.0 for an empty keyword list (nothing to miss)."""
    if not keywords:
        return 1.0
    text_lower = text.lower()
    hits = sum(1 for keyword in keywords if keyword.lower() in text_lower)
    return hits / len(keywords)


def root_cause_keyword_hits(case: GoldenCase, state: AgentState) -> float:
    return keyword_hit_rate(state.diagnosis.root_cause, case.root_cause_keywords)


def remediation_keyword_hits(case: GoldenCase, state: AgentState) -> float:
    steps_text = " ".join(state.remediation_plan.steps)
    return keyword_hit_rate(steps_text, case.remediation_keywords)
