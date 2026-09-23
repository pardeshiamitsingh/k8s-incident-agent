# Spec: HTTP interface

**Status:** draft
**Constitution version this spec complies with:** 1.3.0

## Problem

Nothing external can invoke the agent yet -- `agent.run_agent()` (spec
003) is a Python function nothing outside the codebase calls, and spec
005's resolution logic has no caller either. Constitution v1.3.0 made an
HTTP API the v1 interface (revised from an originally-planned CLI): an
engineer, dashboard, or chat bot submits a `namespace`/`name` and gets
back a cited diagnosis and remediation plan. This spec defines that API --
its request/response shape, how it handles a 10-30+ second diagnosis run
without holding a connection open, and how it controls who can call it,
since it's network-reachable by design.

This spec has a hard dependency on spec 005: without intake resolution, a
caller would have to already know the object's exact `kind`, which
defeats most of the point of exposing this over the network to people who
aren't already deep in `kubectl`. Implementing this spec means
implementing spec 005's `resolve_intake()` too, not just wrapping spec
003's graph.

## Scope

**In:**
- `POST /diagnose` — accepts an intake request (spec 005's schema:
  `namespace`, `name`, `kind?`, `notes?`), resolves it *synchronously*
  (spec 005's resolution is a fast K8s lookup, no LLM call), and:
  - Resolution fails → returns a 4xx immediately, no job created.
  - Resolution succeeds → starts the spec 003 graph run in the
    background, returns `202 Accepted` with a `job_id`.
- `GET /diagnose/{job_id}` — returns the job's current status
  (`running`/`completed`/`failed`) and, once `completed`, the full result
  (resolved object, classification, retrieved chunks, diagnosis,
  remediation plan).
- `GET /healthz` — unauthenticated liveness check.
- Bearer-token authentication on `/diagnose*`, required on every request
  (constitution v1.3.0 -- network-reachable by design, not deferred).
- An in-memory job store (dict, single process) -- no external queue or
  database. Matches this project's existing "zero extra infra" pattern
  (Chroma embedded, no server; this, no job broker).

**Out (deferred):**
- Persisting job results across a process restart -- v1 loses in-flight
  and completed jobs on restart. Acceptable for a dev-stage tool; revisit
  once this runs somewhere restarts matter.
- Any endpoint that mutates cluster state -- doesn't exist anywhere in
  this codebase (constitution principle 1), and this spec doesn't add one.
- Multi-tenancy / per-caller identity -- the bearer token is a single
  shared secret; it answers "is this caller allowed to use the API at
  all," not "which team/user made this request." Fine for v1's single
  trusted-token model; a real identity system is a future spec if needed.
- TLS termination -- assumed to run behind a reverse proxy that
  terminates TLS; this spec's server runs plain HTTP.
- A CLI or web UI built on top of this API -- possible future additions,
  not required for v1 (constitution §4).
- Job result eviction/expiry -- v1 keeps every completed job in memory for
  the process lifetime; unbounded growth on a long-running process is a
  known gap (see Open questions).

## Constitution check

- **Propose-only by default, invoked on demand:** Every job is created by
  an explicit, authenticated `POST /diagnose` call naming a specific
  object -- there is no polling loop, no webhook receiver, and no code
  path that starts a job without a direct API call. This API must never
  be wired to something like an Alertmanager webhook without a further
  constitution amendment (principle 1 is explicit that autonomous/
  webhook-triggered operation is out of scope for v1).
- **Read-only RBAC:** The API process uses the same read-only K8s
  ServiceAccount/kubeconfig as spec 001 already established -- this spec
  adds no new K8s permissions, only a new network entrypoint in front of
  code that already only reads.
- **Local-first, no external LLM calls:** The API orchestrates spec 003's
  graph unchanged -- all reasoning/embedding calls stay local to Ollama.
  The API layer itself makes no LLM calls of its own.
- **Every diagnosis is explainable:** The `GET /diagnose/{job_id}`
  response surfaces spec 003's `Diagnosis`/`RemediationPlan` objects
  whole, citations included -- this spec doesn't summarize or drop the
  citation fields on the way out.
- **Full audit trail:** Every request (who, when, what was asked, what
  job ID was assigned) and every job's full result are logged, per the
  logging-for-debuggability convention already used in `collectors/`,
  `knowledge_base/`, and `agent/`.

## Design

**Auth** (`api/auth.py`): a single shared secret, `INCIDENT_AGENT_API_TOKEN`
(env var, no default -- the app refuses to start without it set). Checked
via `Authorization: Bearer <token>` on every `/diagnose*` request, compared
with `secrets.compare_digest` (not `==`, to avoid a timing side-channel).
Missing or wrong token → `401`. `/healthz` is exempt (a load
balancer/readiness probe shouldn't need a credential just to check the
process is up).

**Request/response schemas** (`api/schemas.py`):
```
DiagnoseRequest:
  namespace: str
  name: str
  kind: Literal["Pod", "Deployment"] | None
  notes: str | None

DiagnoseAccepted (202):
  job_id: str

JobStatus (200, GET /diagnose/{job_id}):
  job_id: str
  status: Literal["running", "completed", "failed"]
  resolved_object: ObjectRef | None       # set once resolution succeeded
  classified_failure_classes: list[str] | None
  retrieved_chunks: list[RunbookChunk] | None
  diagnosis: Diagnosis | None
  remediation_plan: RemediationPlan | None
  error: str | None                        # set only if status == "failed"
```
`resolved_object` is always present once `202` is returned (resolution
already succeeded synchronously by then); the rest populate as the graph
progresses, all `None` until `status == "completed"`.

**`POST /diagnose` handler flow:**
1. Validate the bearer token (401 if invalid).
2. Validate the request body against `DiagnoseRequest` (FastAPI/pydantic
   handles malformed JSON / missing required fields as `400`
   automatically).
3. Call spec 005's `resolve_intake()` synchronously. A `resolution_error`
   → map to `404` (nothing matched) or `409` (ambiguous match, needs
   `kind`) as appropriate, with the error message in the body. No job is
   created.
4. Resolution succeeded → create a job entry (`status="running"`,
   `resolved_object` set), schedule spec 003's `run_agent()` to execute in
   a background thread (`asyncio.to_thread`, since `run_agent()` is
   blocking I/O + LLM calls, and FastAPI's event loop must not block on
   it), return `202` with the `job_id`.
5. When the background run finishes: update the job entry to
   `status="completed"` with the full result, or `status="failed"` with
   `error` set to the exception message if `run_agent()` raised.

**`GET /diagnose/{job_id}` handler:** look up the job; `404` if the ID is
unknown (never existed, or the process restarted and lost it -- same
response either way, since v1 has no persistence to distinguish them).

**Module layout** (new `api/` package):
- `api/schemas.py` -- the request/response models above.
- `api/auth.py` -- the bearer-token dependency.
- `api/jobs.py` -- `JobStore`: in-memory `dict[str, Job]`, `create_job()`,
  `get_job()`, `run_job()` (the `to_thread`-wrapped call into
  `agent.run_agent()`).
- `api/app.py` -- the FastAPI app: route definitions, wires `api/jobs.py`
  and spec 005's `resolve_intake()` together per the handler flow above.

## Acceptance criteria

- `POST /diagnose` without a valid bearer token returns `401` before any
  other processing (resolution, job creation) happens.
- `POST /diagnose` with a body missing `namespace` or `name` returns `422`
  with a field-level validation error (FastAPI/pydantic's actual default
  for request validation, not `400` -- corrected during implementation),
  before `resolve_intake()` is ever called.
- `POST /diagnose` naming an object that doesn't exist returns `404`
  synchronously (same request, no `job_id`), matching spec 005's
  fail-fast resolution error.
- `POST /diagnose` naming an ambiguous same-name Pod/Deployment (spec
  005's unresolved-health case) returns `409` synchronously, same as
  above.
- `POST /diagnose` naming a real object returns `202` with a `job_id`
  within, say, 2 seconds (resolution alone, no LLM call) -- the request
  does not block for the full diagnosis duration.
- Polling `GET /diagnose/{job_id}` for a just-created job returns
  `status="running"` with all result fields `null`, then eventually
  `status="completed"` with every result field populated, matching what
  `agent.run_agent()` would have returned directly for the same object
  (verified against spec 003's own live fixtures).
- `GET /diagnose/{job_id}` for an unknown ID returns `404`.
- An integration test (marked `integration` and `requires_ollama`, per
  the existing convention) runs the full HTTP flow -- `POST /diagnose`
  against a live fixture, poll `GET /diagnose/{job_id}` to completion,
  assert the result matches spec 003's acceptance criteria for that
  fixture.
- `/healthz` returns `200` with no `Authorization` header required.

## Open questions

- **Job result memory growth:** nothing ever evicts a completed job from
  the in-memory store. Fine for a dev/demo process; needs a real answer
  (TTL? max job count? persist to disk?) before this runs anywhere
  long-lived. Not blocking v1 implementation.
- **Background execution model at scale:** `asyncio.to_thread` is simple
  and needs no new infrastructure, but every concurrent job holds a
  Python thread for its full duration (10-30+ seconds, mostly waiting on
  Ollama). Fine at low concurrency (one engineer, occasional use); would
  need revisiting (a real task queue) if this ever serves many concurrent
  callers.
- **Token rotation/multiple tokens:** v1 is a single static token from one
  env var -- rotating it means restarting the process, and there's no way
  to have, say, one token per calling service. Acceptable for v1's single
  trusted-caller assumption; flagged in case that assumption breaks.
- **Where does `INCIDENT_AGENT_API_TOKEN` actually get set/distributed**
  in a real deployment (a secret manager, a K8s Secret mounted as env,
  local `.env`)? This spec assumes it's already in the process
  environment somehow; the actual deployment mechanism is out of scope
  here and depends on where this ends up running (not yet decided).
