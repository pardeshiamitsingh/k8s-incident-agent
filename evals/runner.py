"""Scores every golden case and prints a report (spec 006).

    uv run python -m evals.runner                # keyword scoring only
    uv run python -m evals.runner --llm-judge     # + LLM-as-judge

Exits non-zero if classification accuracy drops below --min-accuracy
(default: report only, no gate -- see spec 006's Out-of-scope on CI
wiring; the exit code exists for a human or CI job to opt into later).
"""

import argparse
import logging
import sys
import time
from pathlib import Path

from .judge import judge_case
from .models import CaseResult, GoldenCase
from .run_from_evidence import run_agent_from_evidence
from .scoring import (
    classification_correct,
    remediation_keyword_hits,
    root_cause_keyword_hits,
)

logger = logging.getLogger(__name__)

GOLDEN_DIR = Path(__file__).parent / "golden"


def load_golden_cases(golden_dir: Path = GOLDEN_DIR) -> list[GoldenCase]:
    return [
        GoldenCase.model_validate_json(path.read_text())
        for path in sorted(golden_dir.glob("*.json"))
    ]


def run_case(case: GoldenCase, use_llm_judge: bool) -> CaseResult:
    start = time.monotonic()
    state = run_agent_from_evidence(case.evidence, notes=None)
    latency = time.monotonic() - start

    judge_score = None
    judge_rationale = None
    if use_llm_judge:
        verdict = judge_case(case, state)
        judge_score = verdict.score
        judge_rationale = verdict.rationale

    return CaseResult(
        case_id=case.id,
        classification_correct=classification_correct(case, state),
        root_cause_keyword_hits=root_cause_keyword_hits(case, state),
        remediation_keyword_hits=remediation_keyword_hits(case, state),
        llm_judge_score=judge_score,
        llm_judge_rationale=judge_rationale,
        latency_seconds=latency,
        diagnosis=state.diagnosis,
        remediation_plan=state.remediation_plan,
    )


def print_report(results: list[CaseResult], use_llm_judge: bool) -> None:
    for result in results:
        print(f"=== {result.case_id} ===")
        print(f"  classification_correct: {result.classification_correct}")
        print(f"  root_cause_keyword_hits: {result.root_cause_keyword_hits:.2f}")
        print(f"  remediation_keyword_hits: {result.remediation_keyword_hits:.2f}")
        if use_llm_judge:
            print(f"  llm_judge_score: {result.llm_judge_score}")
            print(f"  llm_judge_rationale: {result.llm_judge_rationale}")
        print(f"  latency_seconds: {result.latency_seconds:.2f}")
        print(f"  root_cause: {result.diagnosis.root_cause}")
        print(f"  remediation_steps: {result.remediation_plan.steps}")
        print()

    n = len(results)
    accuracy = sum(r.classification_correct for r in results) / n
    mean_root_cause_hits = sum(r.root_cause_keyword_hits for r in results) / n
    mean_remediation_hits = sum(r.remediation_keyword_hits for r in results) / n
    latencies = sorted(r.latency_seconds for r in results)
    mean_latency = sum(latencies) / n
    p95_latency = latencies[int(0.95 * (n - 1))]

    print("=== aggregate ===")
    print(f"  cases: {n}")
    print(f"  classification_accuracy: {accuracy:.2%}")
    print(f"  mean_root_cause_keyword_hits: {mean_root_cause_hits:.2f}")
    print(f"  mean_remediation_keyword_hits: {mean_remediation_hits:.2f}")
    if use_llm_judge:
        mean_judge_score = sum(r.llm_judge_score for r in results) / n
        print(f"  mean_llm_judge_score: {mean_judge_score:.2f}")
    print(f"  mean_latency_seconds: {mean_latency:.2f}")
    print(f"  p95_latency_seconds: {p95_latency:.2f}")

    return accuracy


def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    parser = argparse.ArgumentParser()
    parser.add_argument("--llm-judge", action="store_true")
    parser.add_argument("--min-accuracy", type=float, default=0.0)
    args = parser.parse_args()

    cases = load_golden_cases()
    if not cases:
        print(f"no golden cases found under {GOLDEN_DIR}", file=sys.stderr)
        sys.exit(1)

    results = [run_case(case, use_llm_judge=args.llm_judge) for case in cases]
    accuracy = print_report(results, use_llm_judge=args.llm_judge)

    if accuracy < args.min_accuracy:
        print(
            f"classification accuracy {accuracy:.2%} below threshold "
            f"{args.min_accuracy:.2%}",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
