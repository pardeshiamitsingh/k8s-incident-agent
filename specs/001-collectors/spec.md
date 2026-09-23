# Spec: K8s evidence collectors

**Status:** draft
**Constitution version this spec complies with:** 1.1.0

## Problem

Before the agent can classify, retrieve, or diagnose anything, it needs a
read-only, structured way to pull raw evidence about a broken Kubernetes
object: its recent events, its current state (the `describe`-equivalent
data), and its container logs. This is the foundation phase — every
downstream stage (Phase 2 retrieval, Phase 3 diagnosis) consumes whatever
shape this collector produces. Getting the evidence shape right now avoids
every later phase guessing at an unstable interface.

## Scope

**In:**
- A Python module wrapping the `kubernetes` client that, given an object
  reference (kind + namespace + name — starting with `Pod` and `Deployment`),
  returns:
  - Recent namespace/object-scoped events.
  - A structured describe-equivalent snapshot: phase, conditions, container
    statuses, restart counts, resource requests/limits, owner references.
  - Container logs — current logs, and previous-container logs when a
    container has restarted (needed for CrashLoopBackOff diagnosis).
- Auth support for both local kubeconfig (dev, against kind/minikube) and
  in-cluster ServiceAccount token (future deployment).
- A small set of intentionally broken `Deployment` fixtures for manual and
  automated testing: bad image (`ImagePullBackOff`), memory limit too low
  (`OOMKilled`), missing `ConfigMap` reference
  (`CreateContainerConfigError`), and an unschedulable resource request
  (`Pending`).
- Deployment expansion: when the input `ObjectRef` is a `Deployment`, look
  up its owned Pods (via owner reference) and collect full evidence for
  each of them too, alongside the Deployment-level snapshot. Spec 005
  (incident intake) always resolves to a single object reference and
  explicitly leaves this expansion to this spec.

**Out (deferred to later specs):**
- Failure classification (Phase 3).
- RAG retrieval of runbooks (Phase 2).
- Prometheus metrics collection (optional per constitution tech stack —
  revisit only if a later spec needs it).
- Loki log integration (constitution prefers Loki when available, but v1 of
  this spec uses the K8s API's log endpoint directly; Loki fallback logic is
  its own future spec once Loki is actually in the target cluster).
- Resolving a user's incident report into a concrete `ObjectRef` (Phase 5 —
  Incident intake, spec 005). This spec assumes the caller already has a
  single `ObjectRef` in hand (Pod or Deployment); it is pull-based, one-shot
  collection, invoked on demand — never continuous or autonomous.

## Constitution check

- **Propose-only by default:** Collectors only ever call `get`/`list`/`watch`
  against the K8s API — no mutation is possible from this code path.
- **Read-only RBAC:** The ServiceAccount/kubeconfig context used needs only
  `get`/`list`/`watch` on `pods`, `events`, `deployments`, `configmaps`, and
  the `pods/log` subresource. No other verbs or resources are requested.
- **Local-first, no external LLM calls:** This spec makes no LLM or
  embedding calls at all — it's pure K8s API I/O.
- **Every diagnosis is explainable:** Not directly applicable to collection
  itself, but this spec exists *to enable* explainability — the structured
  evidence it returns is what later stages must cite. Output must stay
  structured (typed models), not opaque text blobs, so later phases can
  reference specific fields.
- **Full audit trail:** Collected evidence must be timestamped and fully
  serializable (JSON-able) so it can be logged and, later, written into the
  postmortem knowledge base without a re-shaping step.

## Design

**Data shapes** (pydantic models, to be reused by every later phase):

- `ObjectRef` — `kind`, `namespace`, `name`.
- `K8sEvent` — `reason`, `message`, `type`, `count`, `first_seen`, `last_seen`,
  `source_component`.
- `ContainerStatus` — `name`, `state` (waiting/running/terminated + reason),
  `restart_count`, `image`, `resource_requests`, `resource_limits`.
- `ObjectDescribeSnapshot` — `phase`, `conditions`, `container_statuses:
  list[ContainerStatus]`, `owner_references`.
- `LogsSnapshot` — `current: str | None`, `previous: str | None` (previous
  populated only when the container has a prior terminated state).
- `IncidentEvidence` — `object_ref`, `collected_at`, `events:
  list[K8sEvent]`, `describe: ObjectDescribeSnapshot`, `logs:
  dict[container_name, LogsSnapshot]`, `pods: list[IncidentEvidence]`
  (recursive/self-referential — empty for a bare Pod target; populated with
  one `IncidentEvidence` per owned Pod when `object_ref.kind ==
  "Deployment"`). Recursive rather than a separate response shape so every
  downstream consumer (classifier, retriever, diagnoser) handles one type
  instead of branching on whether it received a Pod-shaped or
  Deployment-shaped result.

**Module layout** (under a new `collectors/` package):
- `collectors/models.py` — the pydantic models above.
- `collectors/k8s_client.py` — client construction; picks in-cluster config
  if present, else local kubeconfig context.
- `collectors/events.py` — `get_events(object_ref) -> list[K8sEvent]`.
- `collectors/describe.py` — `get_describe(object_ref) ->
  ObjectDescribeSnapshot`.
- `collectors/logs.py` — `get_logs(object_ref) -> dict[str, LogsSnapshot]`.
- `collectors/collect.py` — `collect_evidence(object_ref) ->
  IncidentEvidence`, composing the three above into one call. When
  `object_ref.kind == "Deployment"`, it also looks up owned Pods (via owner
  reference) and calls itself recursively for each to populate `pods`. This
  is the only entrypoint later phases (and eventually the LangGraph
  "collect" node) should import.

**Fixtures:** stored under `fixtures/broken-deployments/` as plain YAML
manifests, one per failure class, applied to the local kind/minikube cluster
from Phase 0. Kept separate from `evals/` (which the template references) —
`evals/` is for the golden incident set with expected diagnoses (Phase 6),
fixtures here are just for exercising the collector itself.

## Acceptance criteria

Applied against each fixture in `fixtures/broken-deployments/`:

- `ImagePullBackOff` fixture: `collect_evidence` returns a `describe`
  snapshot with the failing container's `state.waiting.reason ==
  "ImagePullBackOff"`, and at least one event with reason
  `Failed`/`ErrImagePull`.
- `OOMKilled` fixture: container status shows `state.terminated.reason ==
  "OOMKilled"`, and `logs.previous` is non-empty (last output before the
  kill).
- `CreateContainerConfigError` fixture (missing ConfigMap): event reason
  references the missing ConfigMap by name; container never reaches
  `running`.
- `Pending`/unschedulable fixture: `describe.phase == "Pending"`, events
  include a `FailedScheduling` reason with the scheduler's message.
- All four: `collect_evidence` completes without raising, returns valid
  JSON-serializable output, and every field the assertions above check is
  non-null/non-empty as specified.
- Given a `Deployment` `ObjectRef` owning 3 Pods: `collect_evidence` returns
  `IncidentEvidence.pods` with exactly 3 entries, one per owned Pod, each a
  fully populated `IncidentEvidence` (own `events`, `describe`, `logs`) with
  its own `pods` field empty.
- Given a `Pod` `ObjectRef` (not a Deployment): `IncidentEvidence.pods` is an
  empty list.
- Unit tests cover `events.py`, `describe.py`, and `logs.py` individually
  against a mocked K8s API client (no live cluster required for CI).
- An integration test (marked separately, requires a live kind/minikube
  cluster) runs `collect_evidence` against each applied fixture and checks
  the criteria above.

## Open questions

- Kubeconfig context selection for local dev: assume current context, or
  require an explicit `--context` / env var so this doesn't silently point
  at the wrong cluster?
- Should `describe.py` capture the full K8s API object (maximal fidelity)
  or a curated subset (smaller, more stable for prompts later)? Leaning
  curated subset per principle 4 (explainability needs signal, not noise),
  but worth confirming before Phase 3 locks in prompt design around it.
- Sync vs. async client calls — LangGraph can run either, but async may
  matter once Phase 5 adds a polling loop. Defer decision, but flag that a
  sync choice here may need revisiting.
- Where do fixture manifests get applied/torn down from — a `make fixtures`
  target, a pytest fixture that shells out to `kubectl apply`, or documented
  manual steps? Needs a decision before Phase 0/1 tooling is written up.
