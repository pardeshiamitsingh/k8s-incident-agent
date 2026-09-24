"""RQ worker entrypoint (spec 009).

A separate process from the API -- run one or more of these to scale
diagnosis-running capacity independently of API capacity:

    uv run python -m api.worker

Uses the same `INCIDENT_AGENT_REDIS_URL` env var the API process reads
(see `api/jobs.py`), so both point at the same Redis by default without
extra configuration.
"""

import logging

from rq import Queue, Worker

from .jobs import get_redis_connection

logger = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    connection = get_redis_connection()
    queue = Queue("diagnosis", connection=connection)
    worker = Worker([queue], connection=connection)
    logger.info("starting worker, listening on queue '%s'", queue.name)
    worker.work()


if __name__ == "__main__":
    main()
