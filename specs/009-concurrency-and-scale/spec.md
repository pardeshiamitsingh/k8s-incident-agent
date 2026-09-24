# Spec: Concurrency and scale

**Status:** draft
**Constitution version this spec complies with:** 1.5.0

## Problem

Today's system is hard-capped at one process on one machine: the job
store is a plain in-memory dict (`api/jobs.py`), and diagnosis execution
runs via `asyncio.to_thread` directly inside the API process. Neither
survives a restart, neither can be shared across multiple API processes,
and nothing bounds how much work gets accepted versus how much Ollama can
actually process concurrently -- work just queues silently, with no
backpressure signal to the caller. This spec replaces both with Redis +
an RQ task queue, scoped to real multi-process scaling on a single
machine (not a distributed cluster -- see Open questions for why that's
a deliberate line, not an oversight).

## Scope

**In:**
- **Job store on Redis**, replacing `api/jobs.py`'s in-memory dict. Same
  public interface (`create_job`, `get_job`) so `api/app.py`'s route code
  barely changes. Each job key carries a TTL (default 24h) -- fixes spec
  007's "nothing ever evicts a completed job" gap as a side effect of the
  storage move, not a separate mechanism.
- **RQ task queue** replacing direct `asyncio.to_thread` execution.
  `POST /diagnose` (and each resolved mention in `POST /diagnose/query`)
  enqueues a job instead of spawning a background thread in the API
  process itself. A separate `rq worker` process (or several) pulls jobs
  off the queue and runs `agent.run_agent()`.
- **Explicit backpressure**: before enqueueing, check the queue's current
  depth against a configurable `MAX_IN_FLIGHT_JOBS`; over that, return
  `429` instead of silently accepting unbounded work.
- **Chroma moves to server mode** (`chroma run`, connected via
  `langchain_chroma.Chroma(host=..., port=...)`), not embedded
  `PersistentClient` -- multiple worker processes hitting an embedded
  `PersistentClient` concurrently is exactly the fragile pattern spec
  004 already proved out empirically (a stale read from a separate live
  process). Scaling worker count without fixing this would just
  reintroduce that bug at a larger, harder-to-diagnose scale.
- Operational guidance for Ollama concurrency (`OLLAMA_NUM_PARALLEL`) --
  documented, not new application code; see Open questions for why
  actually orchestrating multiple Ollama instances is deferred.

**Out (deferred):**
- Multi-*machine* scaling (a real distributed deployment, load balancer
  in front of multiple hosts, etc.) -- this spec is single-machine,
  multi-process only. A different spec, and likely a different set of
  trade-offs (network partitions, service discovery), not a natural
  extension of this one.
- Swapping Ollama for a different model-serving stack (vLLM, TGI, etc.)
  -- the constitution's tech-stack commitment to Ollama stays; this spec
  only tunes concurrency within that commitment.
- Queueing `POST /diagnose/query`'s decomposition step itself (still a
  synchronous LLM call in the request path) -- only the diagnosis
  *execution* (collect→plan) moves to the queue. Decomposition adds real
  latency to that endpoint's response time already; queueing it too would
  mean a second polling mechanism for resolution itself, a bigger
  redesign than this spec takes on.
- Redis/RQ high availability (replication, sentinel, persistence tuning)
  -- a single local Redis instance is the assumed deployment for v1,
  same "one operator, one machine" spirit as everything before it.

## Constitution check

- **Propose-only by default:** Unaffected -- still one explicit,
  authenticated request per job, whether synchronous resolution or
  queued execution.
- **Read-only RBAC:** Unaffected -- workers use the exact same read-only
  K8s client code as before, just running in a different process.
- **Local-first, no external LLM calls:** Unaffected. Redis, RQ, and
  Chroma server mode are all local infrastructure the operator runs
  themselves -- no data leaves the machine, no third-party call is
  introduced. This is a break from the *pattern* of minimal infra (not a
  Core Principle), named explicitly in constitution v1.5.0.
- **Every diagnosis is explainable:** Unaffected -- the same `Diagnosis`/
  `RemediationPlan` schema validation applies regardless of which process
  runs `agent.run_agent()`.
- **Full audit trail:** Improved, not just preserved -- Redis-backed jobs
  survive an API process restart (today's in-memory store loses
  everything), so a job's outcome is recoverable for longer than the
  process that started it happened to stay alive.

## Design

**Job store** (`api/jobs.py`, rewritten): `Job` becomes a Pydantic model
(from a `dataclass`) so it round-trips through Redis as JSON directly
(`model_dump_json()`/`model_validate_json()`), no separate serialization
layer needed.
```
RedisJobStore:
  create_job(resolved_object) -> Job       # SET job:<id>, TTL applied
  get_job(job_id) -> Job | None            # GET job:<id>
  save(job: Job) -> None                   # re-SET, same TTL policy
```
`create_job`/`get_job` keep the exact same call signature `api/app.py`
already uses -- the route handlers themselves change minimally.

**Task queue** (new `api/tasks.py`): a module-level function RQ can
import by reference (RQ serializes a path to the function, not a
closure):
```
run_diagnosis_job(job_id: str, resolved_object: ObjectRef, notes: str | None) -> None
```
Same body as today's `JobStore.run_job`, adjusted to `get_job`/`save`
against Redis instead of mutating an in-process dict under a lock (the
lock goes away entirely -- Redis's own atomicity per key replaces it).

**API route change** (`api/app.py`): `_start_diagnosis_job` becomes:
```
def _start_diagnosis_job(resolved_object, notes) -> Job:
    if queue.count >= MAX_IN_FLIGHT_JOBS:
        raise HTTPException(status_code=429, detail="too many in-flight diagnoses, retry shortly")
    job = job_store.create_job(resolved_object)
    queue.enqueue(run_diagnosis_job, job.job_id, resolved_object, notes)
    return job
```
No more `asyncio.create_task`/`_background_tasks` bookkeeping -- RQ's
queue is the thing holding the work now, not an in-process task set.

**Worker process** (new entrypoint, `api/worker.py` or a documented `rq
worker` invocation against `api.tasks`): runs independently of the API
process, scaled by running more of them. Each worker's own `run_agent()`
call still goes through the same `collectors`/`knowledge_base`/`agent`
code unchanged -- this spec only changes *where* that code runs, not
what it does.

**Chroma server mode**: `knowledge_base/ingest.py`'s `get_vector_store()`
gains a mode switch -- `host`/`port` from env vars when set, falling back
to today's `persist_directory` embedded mode for local dev/tests that
don't need multi-process safety (keeps `tests/integration/
test_knowledge_base_smoke.py`'s existing isolated-embedded-store pattern
working unchanged).

## Acceptance criteria

- With the API process restarted mid-poll, `GET /diagnose/{job_id}` for a
  job created before the restart still returns its current status --
  proves the job survived in Redis, not just in the process that created
  it.
- Two API processes (e.g. two `uvicorn` instances behind a simple
  round-robin, or just two terminals hitting different ports against the
  same Redis) can both serve `GET /diagnose/{job_id}` for a job created
  via the *other* process.
- Submitting more than `MAX_IN_FLIGHT_JOBS` concurrent diagnoses returns
  `429` for the overflow requests, not silent queueing.
- Killing the worker process mid-job and restarting it does not corrupt
  the job's Redis state -- it's left in `running` (RQ's own job-retry/
  failure semantics apply, not addressed further here) rather than
  silently vanishing.
- Running 3+ worker processes concurrently against Chroma server mode,
  each independently calling `retrieve_runbooks()` and
  `ingest_postmortem()`, shows no stale-read failures of the kind spec
  004 hit with embedded `PersistentClient` -- verified by adapting that
  spec's own regression test to run against multiple live worker
  processes instead of a single one.
- The existing single-process test suite (`tests/integration/
  test_api_smoke.py`, etc.) still passes unmodified against the
  embedded-Chroma/no-Redis local dev path -- this spec adds a scaled
  deployment option, it doesn't remove the simple one.

## Open questions

- **Why single-machine, not distributed:** going further (multiple
  *hosts*) means solving problems this spec doesn't touch at all --
  network partitions between API/worker/Redis, service discovery,
  probably a real load balancer. Scoping to one machine first means this
  spec's Redis/RQ/Chroma-server changes are validated before that much
  bigger step is even attempted.
- **Ollama concurrency is documented, not orchestrated:** running
  multiple Ollama instances and load-balancing across them from workers
  would meaningfully increase real throughput, but needs its own design
  (config for multiple base URLs, a load-balancing strategy in
  `agent/llm.py`) -- left as follow-on work, not silently assumed to be
  "free" once Redis/RQ land.
- **`MAX_IN_FLIGHT_JOBS`'s actual value:** no default is validated here:
  depends entirely on the deployment's Ollama concurrency capacity, which
  this spec doesn't measure. A placeholder for now; needs real load
  testing once this is running somewhere.
- **RQ job retry/failure policy:** RQ has its own retry/backoff
  primitives; this spec doesn't decide whether a failed diagnosis should
  auto-retry or just surface as `status: "failed"` (today's behavior).
  Worth a deliberate choice, not a default left unexamined.
