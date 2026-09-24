"""Redis-backed job store (spec 009, superseding spec 007's in-memory one).

Replaces the in-memory dict so job state survives a process restart and
is shared across multiple API/worker processes -- the whole point of
this spec. Same public interface (`create_job`, `get_job`) as the
in-memory version it replaces, so `api/app.py`'s route handlers barely
change.
"""

import logging
import os
import uuid
from typing import Literal

import redis
from pydantic import BaseModel

from agent.models import Diagnosis, RemediationPlan
from collectors.models import ObjectRef
from knowledge_base.models import RunbookChunk

logger = logging.getLogger(__name__)

JobState = Literal["running", "completed", "failed"]

DEFAULT_JOB_TTL_SECONDS = 24 * 60 * 60
KEY_PREFIX = "incident-agent:job:"


class Job(BaseModel):
    job_id: str
    status: JobState
    resolved_object: ObjectRef
    classified_failure_classes: list[str] | None = None
    retrieved_chunks: list[RunbookChunk] | None = None
    diagnosis: Diagnosis | None = None
    remediation_plan: RemediationPlan | None = None
    error: str | None = None


def _redis_url() -> str:
    return os.environ.get("INCIDENT_AGENT_REDIS_URL", "redis://localhost:6379/0")


def get_redis_connection() -> redis.Redis:
    return redis.Redis.from_url(_redis_url())


class RedisJobStore:
    """No in-process lock needed -- Redis's own per-key atomicity replaces
    it; `create_job`/`save` are each a single `SET`."""

    def __init__(self, connection: redis.Redis, ttl_seconds: int = DEFAULT_JOB_TTL_SECONDS):
        self._redis = connection
        self._ttl = ttl_seconds

    def create_job(self, resolved_object: ObjectRef) -> Job:
        """Creates a new `running` job for an already-resolved object and
        stores it. Does not start the agent graph itself -- see
        `api/tasks.py`'s `run_diagnosis_job`, enqueued by the caller."""
        job = Job(
            job_id=str(uuid.uuid4()), status="running", resolved_object=resolved_object
        )
        self.save(job)
        logger.info(
            "created job %s for %s %s/%s",
            job.job_id, resolved_object.kind,
            resolved_object.namespace, resolved_object.name,
        )
        return job

    def get_job(self, job_id: str) -> Job | None:
        raw = self._redis.get(KEY_PREFIX + job_id)
        if raw is None:
            return None
        return Job.model_validate_json(raw)

    def save(self, job: Job) -> None:
        self._redis.set(KEY_PREFIX + job.job_id, job.model_dump_json(), ex=self._ttl)


job_store = RedisJobStore(get_redis_connection())
