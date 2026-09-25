# Constitution: k8s-incident-agent

This document is the source of truth for this project's mission, non-negotiable
principles, tech stack, and roadmap. Every spec written under `specs/` must be
consistent with this constitution. If a spec conflicts with it, the constitution
wins — either the spec is revised or this document is amended explicitly
(see Governance).

## 1. Mission

Build an AI agent that, given a user-reported Kubernetes incident, inspects
live cluster evidence plus a retrieval-augmented knowledge base of runbooks
and past incidents, and produces a clear, trustworthy diagnosis and
remediation plan — running entirely on local infrastructure (Ollama), so no
cluster data or logs leave the environment.

The agent runs on demand: an engineer describes or points at an incident,
and the agent should turn that report into a root cause and a proposed fix
faster than the engineer's own first 10 minutes of manual triage would. It
does not run autonomously in the cluster or watch for incidents on its own.

## 2. Core Principles

These are non-negotiable for v1 and any spec that violates them must be
rejected or the constitution amended first.

1. **Propose-only by default, invoked on demand.** The agent runs only when
   a user reports an incident (via CLI query or a pointer to an object) — it
   does not run autonomously or continuously watch the cluster. Given an
   incident, it diagnoses and writes a remediation plan; it does not mutate
   cluster state in v1. A human executes the fix. Auto-execution and
   autonomous/always-on operation are explicit future roadmap items, not v1
   assumptions.
2. **Read-only RBAC.** The agent's ServiceAccount may only `get`/`list`/`watch`.
   No `create`/`update`/`patch`/`delete` permissions are granted, even if the
   application code could technically call them.
3. **Local-first, no external LLM calls.** All reasoning and embedding calls
   go through local Ollama models. No incident data, logs, or cluster state
   is sent to a third-party API. **Named exception (v1.2.0):** LangSmith
   tracing may send trace data (queries, retrieved runbook chunks and their
   metadata, and later diagnosis prompts/completions) to LangChain's hosted
   LangSmith service for observability. This is the sole named exception;
   no other external API calls are permitted without a further amendment.
4. **Every diagnosis is explainable.** The agent must cite which evidence
   (events/logs/metrics) and which retrieved knowledge-base entries led to
   its conclusion — no unexplained verdicts.
5. **Full audit trail.** Every diagnosis, retrieved source, and proposed plan
   is logged and written back into the knowledge base as a postmortem entry,
   whether or not the human accepted the plan.

## 3. Tech Stack

| Layer | Choice | Notes |
|---|---|---|
| Orchestration | LangGraph | State machine for collect → classify → retrieve → diagnose → plan |
| Framework | LangChain | Tool wrappers, retrievers, output parsing |
| Observability | LangSmith (hosted) | Tracing only, named exception to principle 3 — see §2.3 |
| LLM (reasoning) | Ollama, local model (start with `qwen2.5:14b` or `llama3.1:8b`, benchmark before locking in) | Must support reliable tool-calling |
| Embeddings | Ollama (`nomic-embed-text` or `mxbai-embed-large`) | Local, no external calls |
| Vector store | Chroma | Embedded (single-process use) or server mode (Phase 9+, multi-process) — both local, no external data flow |
| Job store / task queue | Redis + RQ (Phase 9+) | Named exception to the project's "zero extra infra" pattern (not a Core Principle — see amendment history); still local infra, no external call, principle 3 intact |
| K8s access | Python `kubernetes` client, read-only ServiceAccount | Never cluster-admin |
| Metrics (optional) | `prometheus-api-client` | Only if Prometheus is present in target cluster |
| Logs | Loki API, fallback to `kubectl logs` | Loki preferred when available |
| Target dev cluster | Local kind/minikube | Safe to break; used to build test fixtures |
| Language | Python | — |

## 4. Roadmap

Phases are sequential; each must produce something testable against the
golden incident set before moving on.

- **Phase 0 — Environment setup**: Ollama installed with reasoning +
  embedding models pulled; Chroma running locally; kind/minikube cluster up.
- **Phase 1 — Collectors**: K8s client wrapper pulling events, pod describe,
  logs for a given object. Test fixtures: intentionally broken deployments
  (bad image, low memory limit, missing ConfigMap, etc.).
- **Phase 2 — RAG knowledge base**: Author 10–15 runbook markdown files for
  common failure classes (CrashLoopBackOff, OOMKilled, ImagePullBackOff,
  Pending/Unschedulable, PVC binding failures). Ingest into Chroma, verify
  retrieval quality manually.
- **Phase 3 — LangGraph agent v1**: Collector → Classifier → Retriever →
  Diagnoser → Remediation Planner, linear graph, propose-only output
  (a written report, no execution).
- **Phase 4 — Postmortem loop**: Resolved incidents get written back into the
  RAG store so the system improves over time.
- **Phase 5 — Incident intake**: Given a user's natural-language incident
  report (e.g. "payment-service pods are crashing"), resolve it to one or
  more concrete K8s object references by listing/filtering live cluster
  state. No continuous polling or autonomous watching — this runs only when
  a user submits a report. (Autonomous/always-on triggers, e.g. polling
  cluster events or Alertmanager webhooks, are out of scope for v1 — see
  below.)
- **Phase 6 — Evaluation harness**: Golden set of 15–20 known incidents;
  score root-cause accuracy, remediation quality, latency.
- **Phase 7 — Interface**: an HTTP API is the v1 interface (revised from
  the original "CLI first" plan — see amendment history), async
  job-pattern (`POST` to start, poll a status endpoint for the result,
  since a diagnosis run takes 10-30+ seconds). Network-reachable by
  design, so it requires real access control (a bearer token, checked on
  every request) from v1, not deferred. TLS termination is a deployment
  concern (reverse proxy), not something the API process handles itself.
  A CLI or web UI on top of this API is a possible future addition, not
  required for v1.
- **Phase 8 — Natural-language intake**: fulfills what Phase 5's original
  wording aspired to ("payment-service pods are crashing") but spec 005
  explicitly deferred ("free-text resolution... needs its own constitution
  amendment"). A new endpoint decomposes free text into one or more
  service mentions (local LLM, structured output) and fuzzy-matches each
  against live cluster object names (deterministic string matching, not
  LLM-ranked — same reasoning as Phase 3's Classifier staying LLM-free:
  explainable and testable beats clever). Ambiguous matches are tie-broken
  by health, reusing spec 005's own rule, and still hard-error rather than
  guess when health doesn't disambiguate either. Sits entirely in front of
  the existing `/diagnose` pipeline; changes nothing about intake,
  collection, classification, retrieval, diagnosis, or planning.
- **Phase 9 — Concurrency and scale**: replaces the in-memory job store
  (spec 007's own documented limitation — single process only, nothing
  ever evicted) with Redis, and the direct `asyncio.to_thread` background
  execution with an RQ task queue and separate worker processes, so the
  API and diagnosis-running capacity can scale independently across
  multiple processes on one machine. Scoped deliberately to
  single-machine, multi-process scaling, not a distributed cluster.
  Chroma moves to server mode for this phase (embedded `PersistentClient`
  is not safe for the concurrent multi-process access multiple workers
  would create — learned directly from spec 004's cross-process
  consistency bug). No Core Principle is violated (Redis/RQ are local
  infra the operator runs themselves, not a third-party data flow —
  principle 3 is intact), but it does break the "zero extra infra"
  pattern held since Phase 2 — a deliberate, named trade-off, not a
  silent one.

- **Phase 10 — Web frontend**: fulfills Phase 7's "a CLI or web UI on top
  of this API is a possible future addition." A minimal single-page UI,
  served as static files by the existing FastAPI app (same origin), that
  takes a natural-language query, drives `POST /diagnose/query` and the
  job-polling endpoint, and renders the diagnosis and remediation plan.
  Purely a client of the existing API: it adds no new diagnosis logic,
  and the browser authenticates with the same bearer token as any other
  client (pasted by the user, never embedded server-side). Vanilla
  HTML/JS with no build step and no third-party scripts, so no external
  data flow is introduced. The postmortem form is deferred.

**Explicitly out of scope for v1** (future roadmap, needs a constitution
amendment before being built): auto-execution of remediation steps,
autonomous/continuous cluster watching (polling or webhook-triggered),
multi-cluster support, non-local/hosted LLM usage, Qdrant migration.

## 5. Governance

- This constitution is amended by explicit agreement — not silently
  overridden by a spec or by implementation convenience.
- Any spec under `specs/` that needs to violate a Core Principle must say so
  explicitly and propose an amendment to this file first.
- Version history of this file is the project's record of major direction
  changes; keep amendments as additive edits with a short rationale, not
  silent rewrites.

### Amendment history

- **1.1.0** (2026-09-22): Changed the interaction model from
  continuous/autonomous cluster watching to on-demand, user-initiated
  queries. The agent never runs independently in the cluster — a user
  reports an incident and the agent analyzes it and proposes a remediation.
  Mission (§1), Principle 1 (§2), and Phase 5 (§4, renamed from "Trigger
  mechanism" to "Incident intake") reworded accordingly; autonomous/
  always-on operation moved to explicitly out-of-scope for v1.
- **1.2.0** (2026-09-23): Carved out a named exception to Principle 3 (§2)
  for LangSmith tracing — trace data (queries, retrieved runbook chunks,
  and later diagnosis prompts/completions) may be sent to LangChain's
  hosted LangSmith service for observability. This is a deliberate,
  scoped trade of "fully local" for tracing/debugging value during
  development; it is the *only* named exception to principle 3 and does
  not open the door to other third-party calls without a further
  amendment. Added to the Tech Stack table (§3) as "Observability."
- **1.3.0** (2026-09-23): Revised Phase 7 (§4) from "CLI/log output first"
  to an HTTP API as the v1 interface, async job pattern (diagnosis runs
  take 10-30+ seconds), with bearer-token access control required from
  v1 since the API is network-reachable by design — not localhost-only,
  not deferred. Spec 005's originally-planned CLI entrypoint is
  superseded by this API; its resolution logic is reused as a library
  call from the API's request handler instead.
- **1.4.0** (2026-09-24): Added Phase 8 (§4) — natural-language intake,
  layered entirely in front of the existing `/diagnose` pipeline. Picks up
  exactly what spec 005 named as deferred ("free-text resolution... needs
  its own constitution amendment"). Cross-namespace candidate listing for
  fuzzy matching is a broader read-only RBAC footprint than spec 001's
  single-namespace scope (still only `get`/`list`/`watch`, per principle 2
  — unchanged, just wider) — noted here since it's a real scope increase,
  not silently assumed.
- **1.5.0** (2026-09-24): Added Phase 9 (§4) — concurrency and scale.
  Redis + RQ replace the in-memory job store and `asyncio.to_thread`
  background execution (spec 007's own documented single-process limit),
  and Chroma moves to server mode so multiple worker processes don't
  reintroduce spec 004's cross-process consistency bug at larger scale.
  Added to the Tech Stack table (§3). No Core Principle violated — this
  is new *local* infrastructure, not a third-party data flow — but it is
  an explicit, named break from the "zero extra infra" pattern every
  spec since Phase 2 has held to, accepted deliberately for real
  horizontal scaling rather than assumed silently.
- **1.6.0** (2026-09-25): Added Phase 10 (§4) — a minimal web frontend
  on top of the existing HTTP API, the "web UI" Phase 7 named as a
  possible future addition. No Core Principle violated: it is a static
  client of the existing API, uses the same bearer-token access control,
  and loads no third-party scripts (principle 3 intact). Postmortem
  submission from the UI is deferred to a later spec.

**Version:** 1.6.0 — 2026-09-25
