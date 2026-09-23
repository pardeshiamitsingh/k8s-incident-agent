# Spec: LangGraph agent v1

**Status:** draft
**Constitution version this spec complies with:** 1.2.0

## Problem

Specs 001 and 002 built two capabilities in isolation: pulling structured
evidence about a broken object, and retrieving relevant runbook content.
Neither is useful to an operator on its own -- they need to be wired into
one pipeline that goes from "here's a broken object" to "here's a root
cause and a proposed fix, with citations." This is Phase 3 of the roadmap:
the actual agent, as a LangGraph state machine, propose-only (constitution
principle 1 -- it writes a report, it never executes anything).

## Scope

**In:**
- A LangGraph `StateGraph` with five nodes, run linearly: **Collect →
  Classify → Retrieve → Diagnose → Plan**.
- `AgentState`: the shared state object every node reads/writes.
- **Collect** node: wraps spec 001's `collect_evidence()`.
- **Classify** node: deterministic, rule-based mapping from the evidence's
  K8s `reason` strings (container states, events) to the failure-class
  taxonomy spec 002's runbooks already use -- no LLM call. See Design for
  the full rationale.
- **Retrieve** node: wraps spec 002's `retrieve_runbooks()`, queried with
  the classified failure class(es).
- **Diagnose** node: local LLM call (Ollama, via LangChain's `ChatOllama`)
  producing a structured root-cause diagnosis that cites specific evidence
  fields and specific retrieved runbook chunk IDs.
- **Plan** node: local LLM call producing a structured, propose-only
  remediation plan -- text only, no execution capability exists in this
  spec or anywhere in v1.
- Graph entry point: the initial state is a `resolved_object: ObjectRef`
  (and optional `notes: str`), matching spec 005's already-defined state
  field names exactly, so Phase 5's intake node can later be inserted
  *ahead of* `Collect` without renaming any state field.
- A minimal way to run the graph end-to-end (a Python function taking an
  `ObjectRef`, returning the final `AgentState`) -- a CLI wrapper is
  Phase 7's job, not this spec's.

**Out (deferred to later specs):**
- Incident intake / resolving a user's `namespace/name` input into an
  `ObjectRef` -- that's spec 005's implementation, not built yet. This
  spec's graph starts from an already-resolved `ObjectRef`.
- Any execution of the remediation plan -- constitution principle 1 is
  permanent for v1, not just this spec's scope.
- Postmortem write-back into the knowledge base (Phase 4).
- The evaluation harness / golden incident set scoring (Phase 6) -- this
  spec's acceptance criteria use spec 001's existing fixtures instead.
- A CLI entrypoint (Phase 7).
- Multi-object / fan-out diagnosis when a Deployment's evidence contains
  multiple distinct failure classes across its owned Pods -- v1 classifies
  and diagnoses against the *evidence as a whole* (see Design); per-Pod
  differential diagnosis is a future refinement.

## Constitution check

- **Propose-only by default:** The Plan node's entire output is a written,
  structured plan -- there is no code path anywhere in this spec that
  calls a mutating K8s API verb. This is structural (no client with write
  permissions is ever constructed), not just a prompt instruction.
- **Read-only RBAC:** The Collect node reuses spec 001's client
  construction unchanged; no new verbs are introduced.
- **Local-first, no external LLM calls:** Diagnose and Plan both call
  Ollama exclusively via `langchain_ollama.ChatOllama`, pointed at the
  local server. LangSmith tracing remains the sole named exception
  (constitution v1.2.0), opt-in via env vars, and traces prompts/
  completions, not cluster data leaving through any other path.
- **Every diagnosis is explainable:** Enforced structurally, not just by
  prompt instruction -- the Diagnose node's structured output schema
  *requires* a non-empty list of cited evidence fields and cited runbook
  chunk IDs; a diagnosis with no citations is a schema validation failure,
  not a soft suggestion.
- **Full audit trail:** The full `AgentState` (evidence, classification,
  retrieved chunks, diagnosis, plan) is a single serializable object after
  a graph run -- logged in full (per the logging-for-debuggability
  convention already used in `collectors/` and `knowledge_base/`) so
  Phase 4's postmortem loop has everything it needs without re-deriving
  it.

## Design

**Why the Classify node is deterministic, not an LLM call:** every
failure class in spec 002's runbook taxonomy corresponds almost exactly to
a K8s-native `reason` string this project already captures structurally in
spec 001's models (`ContainerState.reason`, `K8sEvent.reason`) --
`OOMKilled`, `ImagePullBackOff`, `CreateContainerConfigError`, etc. are
literal API values, not something that needs to be inferred from prose. A
lookup table is faster, fully deterministic, and trivially explainable (a
citation is just "the API reported reason=X"); spending an LLM call here
would add latency and non-determinism for a problem that's already solved
by exact string matching.

**`AgentState`** (`agent/state.py`):
```
AgentState:
  resolved_object: ObjectRef
  notes: str | None

  evidence: IncidentEvidence | None
  classified_failure_classes: list[str]        # e.g. ["OOMKilled"]
  retrieved_chunks: list[RunbookChunk]
  diagnosis: Diagnosis | None
  remediation_plan: RemediationPlan | None
```

**Classification table** (`agent/classification.py`): a `dict[str, str]`
mapping known K8s `reason` values to spec 002's failure-class strings
(`"OOMKilled" -> "OOMKilled"`, `"ImagePullBackOff" -> "ImagePullBackOff"`,
`"ErrImagePull" -> "ImagePullBackOff"`, `"FailedScheduling" -> "Pending"`,
`"Evicted" -> "NodePressureEviction"`, `"Unhealthy" -> "ProbeFailure"`,
etc. -- one entry per runbook's `symptoms`). The Classify node walks the
evidence's container states and event reasons (recursing into
`evidence.pods` for a Deployment) and collects every distinct matched
failure class. No match anywhere -> `["Unknown"]`, and the Retrieve node
falls back to a query built from the raw `reason`/`message` text instead
of a clean failure-class label.

**Diagnose node output** (`agent/models.py`):
```
Diagnosis:
  root_cause: str
  cited_evidence: list[str]      # e.g. "container app: state.terminated.reason=OOMKilled"
  cited_runbook_chunks: list[str]  # chunk IDs, e.g. "oom-killed#diagnosis"
```
Produced via LangChain's structured-output binding (`ChatOllama(...)
.with_structured_output(Diagnosis)`), which requires Ollama's tool-calling
support (constitution tech-stack note) -- both `cited_evidence` and
`cited_runbook_chunks` are required, non-empty fields in the schema.

**Plan node output**:
```
RemediationPlan:
  summary: str
  steps: list[str]
  caveats: str | None
```

**Graph wiring** (`agent/graph.py`): a `langgraph.graph.StateGraph` with
edges `collect -> classify -> retrieve -> diagnose -> plan -> END`, no
conditional branches in v1 (a resolution-failure short-circuit is spec
005's concern, added when intake is inserted ahead of `collect`).
`run_agent(object_ref: ObjectRef, notes: str | None = None) -> AgentState`
is the module's single public entrypoint, mirroring spec 001's
`collect_evidence` and spec 002's `retrieve_runbooks` as "the one thing
later code imports."

## Acceptance criteria

- Running `run_agent()` against spec 001's `oom-killed` fixture (live
  cluster) produces `classified_failure_classes == ["OOMKilled"]`,
  `retrieved_chunks` containing at least one `oom-killed#*` chunk, and a
  `diagnosis.root_cause` that is non-empty with a non-empty
  `cited_evidence` and `cited_runbook_chunks`.
- Same, for the `image-pull-backoff`, `create-container-config-error`, and
  `pending-unschedulable` fixtures -- each classifies to its matching
  failure class and retrieves its matching runbook.
- `remediation_plan.steps` is non-empty for every fixture above, and
  contains no field or language implying the plan was executed rather than
  proposed.
- A fixture/evidence with no matching `reason` anywhere classifies to
  `["Unknown"]` and still produces a diagnosis (using the raw-text
  retrieval fallback), rather than the graph erroring out.
- A `Diagnosis` or `RemediationPlan` missing a required structured field
  (e.g. empty `cited_evidence`) fails schema validation rather than
  silently passing through with an empty citation list.
- Unit tests cover the Classify node's lookup table directly (reason string
  in, failure class out) without needing a live cluster or Ollama.
- An integration test (marked `requires_ollama`, mirroring spec 002's
  convention) runs `run_agent()` against each live fixture and checks the
  criteria above.

## Open questions

- ~~**Reasoning model**~~ -- **Resolved:** `llama3.1:8b` (already pulled in
  Phase 0). Not benchmarking `qwen2.5:14b` for v1; revisit if diagnosis
  quality proves inadequate.
- ~~**Diagnose and Plan: one LLM call or two?**~~ -- **Resolved:** two
  separate nodes/calls, matching the roadmap's naming and keeping each
  stage independently testable/scoreable for Phase 6.
- **Multi-failure-class evidence:** when `classified_failure_classes` has
  more than one entry (a Deployment whose Pods show different failure
  reasons), **resolved:** retrieve separately per failure class (`k=3`
  each) and merge, deduping by chunk ID -- keeps each failure class's
  query semantically clean rather than diluting a single joined query
  string across unrelated symptoms.
- **Prompt content for Diagnose/Plan:** this spec defines the *output
  schema* but not the actual system prompt wording -- needs drafting
  during implementation, and probably a few iterations against the live
  fixtures to get citation quality right.
