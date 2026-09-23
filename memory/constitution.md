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
| Vector store | Chroma | Embedded, zero extra infra, local-first |
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
- **Phase 7 — Interface**: CLI/log output first; web UI (for reviewing
  diagnoses) is a stretch goal, not required for v1.

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

**Version:** 1.2.0 — 2026-09-23
