"""Retrieval-only evaluation: dense vs hybrid (spec 014).

For every golden case, classify its frozen evidence, run retrieval exactly
as `retrieve_node` does, and check whether the case's expected runbook
(`GoldenCase.expected_runbooks`, defaulting to the case id, which
matches a runbook file stem) is in the retrieved
top-3-per-class set. No cluster and no LLM needed.

    uv run python -m evals.retrieval_check
"""

import os
import sys
import time

from agent.classification import classify_evidence
from agent.retrieve_node import retrieve_for_failure_classes
from knowledge_base.retrieve import MODE_ENV_VAR

from .runner import load_golden_cases


def _stem(chunk_id: str) -> str:
    return chunk_id.split("#")[0]


def evaluate(mode: str, cases) -> dict:
    os.environ[MODE_ENV_VAR] = mode
    hits, rr_sum, latencies, misses = 0.0, 0.0, [], []
    for case in cases:
        classes = classify_evidence(case.evidence)
        started = time.monotonic()
        chunks = retrieve_for_failure_classes(classes, case.evidence)
        latencies.append(time.monotonic() - started)
        stems = [_stem(c.id) for c in chunks]
        expected = case.expected_runbooks or [case.id]
        found = [e for e in expected if e in stems]
        hits += len(found) / len(expected)
        if found:
            rr_sum += 1.0 / (min(stems.index(e) for e in found) + 1)
        if len(found) < len(expected):
            misses.append(case.id)
    latencies.sort()
    return {
        "mode": mode,
        "hit_rate": hits / len(cases),
        "hits": hits,
        "mrr": rr_sum / len(cases),
        "p95_latency_ms": latencies[max(0, int(len(latencies) * 0.95) - 1)] * 1000,
        "misses": misses,
    }


def main() -> None:
    cases = load_golden_cases()
    if not cases:
        print("no golden cases found", file=sys.stderr)
        sys.exit(1)

    results = [evaluate(mode, cases) for mode in ("dense", "hybrid")]
    print(f"{len(cases)} golden cases (expected runbook in retrieved set)\n")
    print(f"{'mode':8} {'hit rate':>10} {'MRR':>7} {'p95 ms':>9}  misses")
    for r in results:
        print(
            f"{r['mode']:8} {r['hits']:>5.1f}/{len(cases):<3}={r['hit_rate']:.2f} "
            f"{r['mrr']:>7.3f} {r['p95_latency_ms']:>9.0f}  {', '.join(r['misses']) or '-'}"
        )

    dense, hybrid = results
    verdict = "PASS" if hybrid["hit_rate"] >= dense["hit_rate"] else "FAIL"
    print(f"\ngate (hybrid hit rate >= dense): {verdict}")
    sys.exit(0 if verdict == "PASS" else 1)


if __name__ == "__main__":
    main()
