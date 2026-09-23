"""Generates a golden case from real, live-collected evidence (spec 006).

Run against an already-applied, settled fixture:

    uv run python -m evals.generate_golden_case \\
        --id oom-killed --kind Deployment --namespace ns --name oom-killed \\
        --expected-failure-classes OOMKilled \\
        --root-cause-keywords memory OOM limit \\
        --remediation-keywords "memory limit" "resources.limits"

Writes evals/golden/<id>.json. Safe to rerun -- overwrites the existing
file for that id, so regenerating after a fixture's expected symptoms
change is a single command.
"""

import argparse
import logging
from pathlib import Path

from collectors.collect import collect_evidence
from collectors.models import ObjectRef

from .models import GoldenCase

logger = logging.getLogger(__name__)

GOLDEN_DIR = Path(__file__).parent / "golden"


def generate_golden_case(
    case_id: str,
    object_ref: ObjectRef,
    expected_failure_classes: list[str],
    root_cause_keywords: list[str],
    remediation_keywords: list[str],
) -> Path:
    evidence = collect_evidence(object_ref)
    case = GoldenCase(
        id=case_id,
        evidence=evidence,
        expected_failure_classes=expected_failure_classes,
        root_cause_keywords=root_cause_keywords,
        remediation_keywords=remediation_keywords,
    )

    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    out_path = GOLDEN_DIR / f"{case_id}.json"
    out_path.write_text(case.model_dump_json(indent=2) + "\n")
    logger.info("wrote %s", out_path)
    return out_path


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--id", required=True)
    parser.add_argument("--kind", required=True, choices=["Pod", "Deployment"])
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--expected-failure-classes", nargs="+", required=True)
    parser.add_argument("--root-cause-keywords", nargs="+", required=True)
    parser.add_argument("--remediation-keywords", nargs="+", required=True)
    args = parser.parse_args()

    generate_golden_case(
        case_id=args.id,
        object_ref=ObjectRef(kind=args.kind, namespace=args.namespace, name=args.name),
        expected_failure_classes=args.expected_failure_classes,
        root_cause_keywords=args.root_cause_keywords,
        remediation_keywords=args.remediation_keywords,
    )


if __name__ == "__main__":
    main()
