"""RQ worker entrypoint (spec 009).

A separate process from the API -- run one or more of these to scale
diagnosis-running capacity independently of API capacity:

    uv run python -m api.worker

Uses the same `INCIDENT_AGENT_REDIS_URL` env var the API process reads
(see `api/jobs.py`), so both point at the same Redis by default without
extra configuration.

Uses `SimpleWorker`, not RQ's default fork-per-job `Worker`: on macOS,
forking a process that has already started background threads (observed
here from Chroma's grpc support, pulled in once server mode was used)
crashes with SIGSEGV ("crashed on child side of fork pre-exec"), a known
fork-safety hazard rather than a bug in this code. `run_diagnosis_job`
already has its own exception handling, so the isolation `Worker`'s fork
would have bought is barely missed.
"""

import logging

from rq import Queue, SimpleWorker

from .jobs import get_redis_connection

logger = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    connection = get_redis_connection()
    queue = Queue("diagnosis", connection=connection)
    worker = SimpleWorker([queue], connection=connection)
    logger.info("starting worker, listening on queue '%s'", queue.name)
    worker.work()


if __name__ == "__main__":
    main()
