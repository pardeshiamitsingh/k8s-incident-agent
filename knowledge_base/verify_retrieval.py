"""Manual retrieval-quality verification (spec 002 acceptance criteria).

Run after `ingest_runbooks()` has populated the Chroma collection:

    uv run python -m knowledge_base.verify_retrieval

Prints top-k results per representative query for human review -- this is
deliberately not an automated pass/fail check, since "is this retrieval
good enough" is a judgment call, not a fixed assertion.
"""

import logging

from .retrieve import retrieve_runbooks

REPRESENTATIVE_QUERIES = [
    "OOMKilled",
    "container image cannot be pulled",
    "pod stuck pending and never scheduled",
    "DNS lookups failing inside the pod",
    "pod stuck terminating forever",
    "missing ConfigMap causing container to never start",
    "readiness probe failing, pod not receiving traffic",
]


def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    for query in REPRESENTATIVE_QUERIES:
        print(f"=== {query!r} ===")
        for chunk in retrieve_runbooks(query, k=3):
            print(f"  {chunk.id}  (failure_class={chunk.failure_class})")
        print()


if __name__ == "__main__":
    main()
