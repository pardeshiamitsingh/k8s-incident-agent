"""The FastAPI app (spec 007).

POST /diagnose resolves synchronously (fast, no LLM call) and returns a
4xx immediately on failure; on success it schedules the agent graph in a
background thread and returns 202 + job_id. GET /diagnose/{job_id} polls
for status/result.
"""

import asyncio
import logging

from fastapi import Depends, FastAPI, HTTPException, status

from intake.models import IntakeRequest, ResolutionError
from intake.resolve import resolve_intake
from knowledge_base.postmortem import ingest_postmortem

from .auth import get_expected_token, require_bearer_token
from .jobs import job_store
from .schemas import DiagnoseAccepted, JobStatus, PostmortemAccepted, PostmortemRequest

logger = logging.getLogger(__name__)

get_expected_token()  # fail fast at startup if the token isn't configured

app = FastAPI(title="k8s-incident-agent")

# asyncio.create_task() only holds a weak reference to the task it returns;
# without something else referencing it, the task can be garbage-collected
# mid-run. Keeping a strong reference here until each task finishes avoids
# that (see the asyncio docs' own warning on this).
_background_tasks: set[asyncio.Task] = set()


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.post(
    "/diagnose",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_bearer_token)],
)
async def diagnose(request: IntakeRequest) -> DiagnoseAccepted:
    logger.info(
        "diagnose request: namespace=%s name=%s kind=%s",
        request.namespace, request.name, request.kind,
    )
    resolution = resolve_intake(request)
    if isinstance(resolution, ResolutionError):
        code = (
            status.HTTP_404_NOT_FOUND
            if resolution.reason == "not_found"
            else status.HTTP_409_CONFLICT
        )
        logger.info("resolution failed (%s): %s", resolution.reason, resolution.message)
        raise HTTPException(status_code=code, detail=resolution.message)

    job = job_store.create_job(resolution)
    task = asyncio.create_task(
        asyncio.to_thread(job_store.run_job, job.job_id, resolution, request.notes)
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    return DiagnoseAccepted(job_id=job.job_id)


@app.get("/diagnose/{job_id}", dependencies=[Depends(require_bearer_token)])
def get_diagnosis(job_id: str) -> JobStatus:
    job = job_store.get_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="unknown job_id"
        )
    return JobStatus(
        job_id=job.job_id,
        status=job.status,
        resolved_object=job.resolved_object,
        classified_failure_classes=job.classified_failure_classes,
        retrieved_chunks=job.retrieved_chunks,
        diagnosis=job.diagnosis,
        remediation_plan=job.remediation_plan,
        error=job.error,
    )


@app.post(
    "/diagnose/{job_id}/postmortem",
    dependencies=[Depends(require_bearer_token)],
)
def submit_postmortem(job_id: str, request: PostmortemRequest) -> PostmortemAccepted:
    job = job_store.get_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="unknown job_id"
        )
    if job.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"job status is '{job.status}', not 'completed' -- no diagnosis to confirm",
        )

    logger.info(
        "postmortem for job %s: was_correct=%s", job_id, request.was_correct
    )
    if request.was_correct:
        ingest_postmortem(
            job_id=job_id,
            resolved_object=job.resolved_object,
            failure_classes=job.classified_failure_classes or [],
            original_root_cause=job.diagnosis.root_cause,
            actual_root_cause=request.actual_root_cause,
            actual_fix=request.actual_fix,
        )

    return PostmortemAccepted(ingested=request.was_correct)
