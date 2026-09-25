"""The FastAPI app (spec 007, spec 008, spec 009).

POST /diagnose resolves synchronously (fast, no LLM call) and returns a
4xx immediately on failure; on success it enqueues the agent graph onto
an RQ queue (spec 009 -- a separate worker process runs it, not this one)
and returns 202 + job_id. GET /diagnose/{job_id} polls for status/result.
POST /diagnose/query is the natural-language front door (spec 008): it
decomposes and fuzzy-resolves synchronously too (slower -- an LLM call
plus a cluster-wide list per mention -- but still "deciding what to
diagnose," not "doing the diagnosis," so it follows the same
synchronous-resolution/queued-execution split as plain /diagnose).

All routes are plain `def`, not `async def`: every one of them does
blocking work (K8s API calls, a Redis round-trip, sometimes an LLM call)
and none of them need to coordinate with an event loop -- FastAPI runs a
sync route in its own worker thread automatically, which is simpler here
than the asyncio.create_task bookkeeping spec 007/008 needed before RQ
existed to do the equivalent.
"""

import logging
import os
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.staticfiles import StaticFiles
from rq import Queue

from collectors.models import ObjectRef
from intake.models import IntakeRequest, ResolutionError
from intake.resolve import resolve_intake
from knowledge_base.postmortem import ingest_postmortem
from nlintake.decompose import decompose_query
from nlintake.fuzzy_resolve import resolve_mention
from nlintake.models import AmbiguousMatch, DetectedMention, NotFound

from .auth import get_expected_token, require_bearer_token
from .jobs import Job, get_redis_connection, job_store
from .schemas import (
    DiagnoseAccepted,
    JobStatus,
    MentionResult,
    PostmortemAccepted,
    PostmortemRequest,
    QueryRequest,
    QueryResponse,
)
from .tasks import run_diagnosis_job

logger = logging.getLogger(__name__)

get_expected_token()  # fail fast at startup if the token isn't configured

app = FastAPI(title="k8s-incident-agent")

queue = Queue("diagnosis", connection=get_redis_connection())
MAX_IN_FLIGHT_JOBS = int(os.environ.get("INCIDENT_AGENT_MAX_IN_FLIGHT_JOBS", "10"))


def _start_diagnosis_job(resolved_object: ObjectRef, notes: str | None) -> Job:
    """Shared by /diagnose and /diagnose/query -- one job-creation path so
    GET /diagnose/{job_id} behaves identically regardless of which
    endpoint started it. Backpressure here, not silent unbounded
    queueing: past MAX_IN_FLIGHT_JOBS, callers get a 429 and can retry,
    rather than every request being accepted and just queuing behind
    whatever Ollama can actually process concurrently."""
    if queue.count >= MAX_IN_FLIGHT_JOBS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"too many in-flight diagnoses ({queue.count}/{MAX_IN_FLIGHT_JOBS}), "
                "retry shortly"
            ),
        )
    job = job_store.create_job(resolved_object)
    queue.enqueue(run_diagnosis_job, job.job_id, resolved_object, notes)
    return job


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.post(
    "/diagnose",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_bearer_token)],
)
def diagnose(request: IntakeRequest) -> DiagnoseAccepted:
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

    job = _start_diagnosis_job(resolution, request.notes)
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


@app.post("/diagnose/query", dependencies=[Depends(require_bearer_token)])
def diagnose_query(request: QueryRequest) -> QueryResponse:
    logger.info("nl query: %r", request.query)
    mentions = decompose_query(request.query)
    return QueryResponse(mentions=[_resolve_and_start(m) for m in mentions])


def _resolve_and_start(mention: DetectedMention) -> MentionResult:
    outcome = resolve_mention(mention)

    if isinstance(outcome, AmbiguousMatch):
        return MentionResult(
            mentioned_service=mention.mentioned_service,
            notes=mention.notes,
            status="ambiguous",
            candidates=outcome.candidates,
        )
    if isinstance(outcome, NotFound):
        return MentionResult(
            mentioned_service=mention.mentioned_service,
            notes=mention.notes,
            status="not_found",
        )

    job = _start_diagnosis_job(outcome, mention.notes)
    return MentionResult(
        mentioned_service=mention.mentioned_service,
        notes=mention.notes,
        status="resolved",
        job_id=job.job_id,
        resolved_object=outcome,
    )


# Spec 010: static UI, same origin. Mounted last so it can never shadow an
# API route; it serves no data itself (every API call the page makes carries
# the bearer token), so it is intentionally not behind require_bearer_token.
app.mount(
    "/ui",
    StaticFiles(directory=Path(__file__).parent.parent / "frontend", html=True),
    name="ui",
)
