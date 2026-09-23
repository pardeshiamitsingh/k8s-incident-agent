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
  the given namespace, trying `Pod` then `Deployment` when `kind` is
  unspecified. Pods are never matched by literal name search — they're only
  reached via a matched Deployment's owner reference (see spec 001).
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
1. Determine the kind search order: `[kind]` if given, else `["Pod",
   "Deployment"]`.
2. For each kind in order, look up an object with exact `metadata.name ==
   name` in `namespace`.
3. First exact match found wins and resolution stops — search order is the
   disambiguation rule when `kind` is unspecified, so a Pod named
   identically to an unrelated Deployment resolves to the Pod, not an
   ambiguity error. (See open questions — this rule needs confirming.)
4. If nothing matches across all searched kinds → fail-fast error listing
   the namespace, name, and kinds checked.
5. If `kind` is unspecified and the name matches distinct objects across
   *different* kinds is not possible under rule 3's first-match-wins order —
   ambiguity in this spec's v1 scope only arises from a future
   label-selector or fuzzy-match feature, not from this exact-match
   algorithm. (Flagged as an open question below since it changes the
   "hard error on ambiguity" design from the grilling session.)

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
  resolving `X` with no `--kind` returns the Pod, kind-search-order rule 1.
- Given a namespace containing a Deployment named `Y` and no Pod named `Y`:
  resolving `Y` with no `--kind` returns the Deployment.
- Given a namespace containing neither: resolving `Z` returns a
  `resolution_error` naming the namespace, `Z`, and the kinds checked
  (`Pod`, `Deployment`) — the graph does not proceed to collection.
- `--kind Deployment` on a name that only exists as a Pod returns a
  `resolution_error`, not a fallback match — explicit `kind` disables the
  search-order fallback entirely.
- `--notes` text is present, verbatim, in the graph state consumed by the
  diagnoser node (verified via a stub/mock diagnoser in tests, since
  Phase 3's real diagnoser doesn't exist yet).
- CLI positional parsing rejects input that isn't `namespace/name` shaped
  with a clear usage error (not a stack trace).

## Open questions

- **Same-name Pod and Deployment in one namespace:** Design step 3 above
  picks Pod (search-order first-match-wins) silently rather than erroring.
  The grilling session settled on "hard error on ambiguity" for the general
  case, but same-name-across-kinds wasn't explicitly walked through — worth
  confirming whether first-match-wins is actually the intended behavior here
  or whether this specific case should also hard-error and require
  `--kind`.
- Multi-namespace or all-namespaces search (user doesn't know the
  namespace) — out of scope per the required `namespace` field, but likely
  a fast-follow once this is proven, since not every engineer will know the
  exact namespace during an incident.
- Exact RBAC role/binding manifest for the `get`/`list` on `pods` and
  `deployments` this spec needs — deferred to whichever spec first wires up
  the ServiceAccount (likely bundled with spec 001's implementation).
