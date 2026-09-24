"""The RQ task body (spec 009).

A module-level function, not a method or closure -- RQ serializes a
reference to it (`api.tasks.run_diagnosis_job`) that the worker process
imports and calls, so it can't be a bound method or a closure over
per-request state.
"""

import logging

from agent.graph import run_agent
from collectors.models import ObjectRef

from .jobs import get_redis_connection, RedisJobStore

logger = logging.getLogger(__name__)


def run_diagnosis_job(job_id: str, resolved_object: ObjectRef, notes: str | None) -> None:
    """Runs the agent graph and updates the job's Redis record with the
    result, or with the exception message if it raised. Builds its own
    `RedisJobStore`/connection rather than importing the API process's
    `job_store` singleton -- this runs in a separate worker process, not
    the API process, so there is no shared Python object to reuse."""
    job_store = RedisJobStore(get_redis_connection())

    try:
        result = run_agent(resolved_object, notes=notes)
    except Exception as exc:
        logger.exception("job %s failed", job_id)
        job = job_store.get_job(job_id)
        if job is not None:
            job.status = "failed"
            job.error = str(exc)
            job_store.save(job)
        return

    logger.info("job %s completed", job_id)
    job = job_store.get_job(job_id)
    if job is not None:
        job.status = "completed"
        job.classified_failure_classes = result.classified_failure_classes
        job.retrieved_chunks = result.retrieved_chunks
        job.diagnosis = result.diagnosis
        job.remediation_plan = result.remediation_plan
        job_store.save(job)
