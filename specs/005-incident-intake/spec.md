# Spec: Incident intake

**Status:** draft
**Constitution version this spec complies with:** 1.1.0

## Problem

The agent runs on demand (constitution §1, §2 — Principle 1): a user reports
an incident and the agent investigates it. Before any collection,
classification, or diagnosis can happen, that report has to become a
concrete Kubernetes object reference the collectors (spec 001) can act on.
This is Phase 5 of the roadmap, renamed from "Trigger mechanism" to
"Incident intake" when the constitution was amended to 1.1.0 to drop
autonomous/continuous operation. This spec defines exactly what the user
supplies, how it's resolved against live cluster state, and what happens
when resolution fails or is ambiguous.

## Scope

**In:**
- A structured intake schema: `namespace` (required), `name` (required),
  `kind` (optional), `notes` (optional free text).
- Resolution logic: exact top-level name match against cluster objects in
  the given namespace, checking both `Pod` and `Deployment` when `kind` is
  unspecified. If both a Pod and a Deployment share the name, the tie is
  broken by health, not search order — the unhealthy one wins, since during
  an incident that's what the user means (see Design for the exact rule and
  the ambiguous fallback).
- Error handling: a specific, fail-fast error when nothing matches, and a
  hard error (not a silent pick) when the name ambiguously matches more than
  one unrelated object.
- A CLI entrypoint: `incident-agent diagnose <namespace>/<name> [--kind
  Pod|Deployment] [--notes "..."]`.
- Placement: intake is the first node in the Phase 3 LangGraph graph
  (collect → classify → retrieve → diagnose → plan), not a separate
  pre-pipeline script — resolution failures short-circuit the graph via
  state rather than raising before the graph starts.

**Out (deferred to a future spec, needs its own constitution amendment per
the "explicitly out of scope for v1" list):**
- Free-text *resolution* — parsing "payment-service pods are crashing" into
  an object reference via NLP/search. v1 requires the user to name the
  object directly; `notes` carries free text through for the diagnoser's
  use, but intake itself never parses it to find objects.
- Label-selector-based targeting ("all pods matching this label").
- Interactive prompting when flags are omitted.
- Expanding a Deployment into its owned Pods — that's spec 001's
  responsibility (see the `IncidentEvidence.pods` field), not intake's.
  Intake always resolves to exactly **one** `ObjectRef`.

## Constitution check

- **Propose-only by default, invoked on demand:** This spec *is* the
  on-demand entrypoint — the agent only acts when a user runs `diagnose`
  with a specific object. No watching, no polling.
- **Read-only RBAC:** Resolution only needs `get`/`list` on `pods` and
  `deployments` in the given namespace — no new verbs beyond what spec 001
  already requires.
- **Local-first, no external LLM calls:** Resolution is a direct K8s API
  lookup, no LLM/embedding call involved.
- **Every diagnosis is explainable:** The hard-error-on-ambiguity rule
  exists specifically so the agent never silently diagnoses the wrong
  object — an unexplained choice between two unrelated matches would
  violate this principle directly.
- **Full audit trail:** The resolved `ObjectRef` and any `notes` become part
  of the evidence trail logged for the postmortem loop (Phase 4).

## Design

**Input:**
```
IntakeRequest:
  namespace: str
  name: str
  kind: Literal["Pod", "Deployment"] | None
  notes: str | None
```

**Resolution algorithm:**
1. If `kind` is given: look up an object of that kind with exact
   `metadata.name == name` in `namespace`. No match → fail-fast error
   listing the namespace, name, and kind checked. This bypasses everything
   below.
2. If `kind` is unspecified: look up both a Pod and a Deployment with exact
   `metadata.name == name` in `namespace`.
   - Neither matches → fail-fast error listing the namespace, name, and
     kinds checked (`Pod`, `Deployment`).
   - Exactly one matches → resolve to it.
   - Both match (a Pod and a Deployment share the name) → break the tie by
     health, not search order. The object status needed is already on hand
     from the lookup — no extra API call:
     - Pod unhealthy if `status.phase` is not `Running`/`Succeeded`, or is
       `Running` with any `containerStatuses[*].ready == false`.
     - Deployment unhealthy if `status.readyReplicas != status.replicas`
       (including `readyReplicas` unset while `replicas > 0`).
     - Exactly one of the two is unhealthy → resolve to that one.
     - Both unhealthy, or both healthy → hard error: health doesn't
       disambiguate, require `--kind`. Deliberate, not a gap — the Pod and
       Deployment are unrelated objects that happen to share a name, so
       "both broken" is as much a coincidence as "both healthy"; picking
       one by fixed priority risks silently diagnosing the wrong object,
       which is exactly what the hard-error-on-ambiguity rule exists to
       prevent (see Constitution check above).

**Output (LangGraph state fields this node sets):**
```
resolved_object: ObjectRef | None
resolution_error: str | None
notes: str | None
```
The graph's next node (Phase 1 collector) only proceeds if
`resolution_error is None`.

**CLI:**
- `incident-agent diagnose <namespace>/<name>` — positional shorthand,
  `kubectl`-style.
- `--kind Pod|Deployment` — optional, skips the search-order fallback.
- `--notes "<text>"` — optional, passed through as-is.

## Acceptance criteria

- Given a namespace containing a Pod named `X` and no Deployment named `X`:
  resolving `X` with no `--kind` returns the Pod.
- Given a namespace containing a Deployment named `Y` and no Pod named `Y`:
  resolving `Y` with no `--kind` returns the Deployment.
- Given a namespace containing neither: resolving `Z` returns a
  `resolution_error` naming the namespace, `Z`, and the kinds checked
  (`Pod`, `Deployment`) — the graph does not proceed to collection.
- Given a namespace containing both a Pod and a Deployment named `W`, where
  only the Pod is unhealthy (e.g. `CrashLoopBackOff`): resolving `W` with no
  `--kind` returns the Pod.
- Given a namespace containing both a Pod and a Deployment named `W`, where
  only the Deployment is unhealthy (not all replicas ready) and its Pod is
  healthy: resolving `W` with no `--kind` returns the Deployment.
- Given a namespace containing both a Pod and a Deployment named `W`, both
  healthy or both unhealthy: resolving `W` with no `--kind` returns a
  `resolution_error` stating the name is ambiguous and `--kind` is required.
- `--kind Deployment` on a name that only exists as a Pod returns a
  `resolution_error`, not a fallback match — explicit `kind` skips the
  both-kinds lookup and health tie-break entirely, per algorithm step 1.
- `--notes` text is present, verbatim, in the graph state consumed by the
  diagnoser node (verified via a stub/mock diagnoser in tests, since
  Phase 3's real diagnoser doesn't exist yet).
- CLI positional parsing rejects input that isn't `namespace/name` shaped
  with a clear usage error (not a stack trace).

## Open questions

- **Health check freshness:** a Pod/Deployment that's brand-new (e.g. still
  `ContainerCreating`, not yet `Ready`, but not actually broken) reads as
  "unhealthy" under the same-name tie-break rule, same as a genuinely broken
  one — resolution doesn't distinguish "still starting up" from "actually
  incident-worthy." Acceptable for v1 (the user is naming it during an
  active incident, unlikely to coincide with a fresh rollout), but worth
  flagging if it causes surprises.
- Multi-namespace or all-namespaces search (user doesn't know the
  namespace) — out of scope per the required `namespace` field, but likely
  a fast-follow once this is proven, since not every engineer will know the
  exact namespace during an incident.
- Exact RBAC role/binding manifest for the `get`/`list` on `pods` and
  `deployments` this spec needs — deferred to whichever spec first wires up
  the ServiceAccount (likely bundled with spec 001's implementation).
