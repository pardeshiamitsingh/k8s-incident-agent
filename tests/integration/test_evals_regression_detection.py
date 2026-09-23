"""Proves the harness actually detects a real regression, not just that it
runs without erroring (spec 006's own acceptance criterion).

Requires a local Ollama server (the Diagnose/Plan nodes still run for
real) -- not run by default:

    uv run pytest -m requires_ollama tests/integration/test_evals_regression_detection.py
"""

import pytest

from agent import classification
from evals.runner import load_golden_cases, run_case

pytestmark = pytest.mark.requires_ollama


def test_removing_oomkilled_mapping_drops_classification_accuracy(monkeypatch):
    cases = [
        c for c in load_golden_cases()
        if "oom" in c.id or c.id == "multi-failure-deployment"
    ]
    assert cases, "expected at least one OOM-related golden case to exist"

    baseline = {c.id: run_case(c, use_llm_judge=False).classification_correct for c in cases}
    assert all(baseline.values()), "expected all OOM-related cases to pass before breaking anything"

    broken_table = dict(classification.REASON_TO_FAILURE_CLASS)
    del broken_table["OOMKilled"]
    monkeypatch.setattr(classification, "REASON_TO_FAILURE_CLASS", broken_table)

    broken = {c.id: run_case(c, use_llm_judge=False).classification_correct for c in cases}
    assert not any(broken.values()), (
        f"expected every OOM-related case to fail classification once the "
        f"OOMKilled mapping is removed, got {broken}"
    )
