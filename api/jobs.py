"""In-memory job store (spec 007).

No external queue or database -- matches this project's existing "zero
extra infra" pattern (embedded Chroma, no server; this, no job broker).
Jobs are lost on process restart; see spec 007's Open questions.
"""

import logging
import threading
import uuid
from dataclasses import dataclass
from typing import Literal

from agent.graph import run_agent
from agent.models import Diagnosis, RemediationPlan
from collectors.models import ObjectRef
from knowledge_base.models import RunbookChunk

logger = logging.getLogger(__name__)

JobState = Literal["running", "completed", "failed"]


@dataclass
class Job:
    job_id: str
    status: JobState
    resolved_object: ObjectRef
    classified_failure_classes: list[str] | None = None
    retrieved_chunks: list[RunbookChunk] | None = None
    diagnosis: Diagnosis | None = None
    remediation_plan: RemediationPlan | None = None
    error: str | None = None


class JobStore:
    """Thread-safe in-memory job store. A single instance (`job_store`
    below) is shared for the process lifetime."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def create_job(self, resolved_object: ObjectRef) -> Job:
        """Creates a new `running` job for an already-resolved object and
        stores it. Does not start the agent graph itself -- see
        `run_job`."""
        job = Job(
            job_id=str(uuid.uuid4()), status="running", resolved_object=resolved_object
        )
        with self._lock:
            self._jobs[job.job_id] = job
        logger.info(
            "created job %s for %s %s/%s",
            job.job_id, resolved_object.kind,
            resolved_object.namespace, resolved_object.name,
        )
        return job

    def get_job(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def run_job(
        self, job_id: str, resolved_object: ObjectRef, notes: str | None
    ) -> None:
        """Runs the agent graph and updates the job in place with the
        result, or with the exception message if it raised. Blocking --
        the caller (`api/app.py`) is responsible for running this off the
        event loop, e.g. via `asyncio.to_thread`."""
        try:
            result = run_agent(resolved_object, notes=notes)
        except Exception as exc:
            logger.exception("job %s failed", job_id)
            with self._lock:
                job = self._jobs[job_id]
                job.status = "failed"
                job.error = str(exc)
            return

        logger.info("job %s completed", job_id)
        with self._lock:
            job = self._jobs[job_id]
            job.status = "completed"
            job.classified_failure_classes = result.classified_failure_classes
            job.retrieved_chunks = result.retrieved_chunks
            job.diagnosis = result.diagnosis
            job.remediation_plan = result.remediation_plan


job_store = JobStore()
