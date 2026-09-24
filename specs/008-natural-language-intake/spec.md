# Spec: Natural-language intake

**Status:** draft
**Constitution version this spec complies with:** 1.4.0

## Problem

Every existing entrypoint (`POST /diagnose`) requires the caller to already
know the exact `namespace`/`name` of the broken object. A real incident
report doesn't look like that -- it looks like "my payment system isn't
working, also my secrets are missing." This spec adds a natural-language
front door that decomposes a free-text report into one or more concrete
targets and starts a normal diagnosis for each one it can resolve.

This is exactly what spec 005 named as deferred ("free-text resolution...
needs its own constitution amendment") and what the original Phase 5
roadmap wording aspired to before spec 005 scoped it down to exact-name
matching. Constitution v1.4.0 picks that back up as its own phase.

## Scope

**In:**
- `POST /diagnose/query`, body `{"query": "<free text>"}`.
- **Decomposition**: one local LLM call (structured output, mirroring
  `Diagnosis`/`RemediationPlan`'s pattern) turns the free text into a list
  of `{mentioned_service, notes}` entries -- one per distinct thing the
  report names as broken.
- **Fuzzy resolution**: each mention is matched against live object names
  (Deployments only -- see Open questions) across namespaces, using
  deterministic string matching (substring, then close-match fallback),
  *not* an LLM ranking. Same reasoning as spec 003's Classifier staying
  LLM-free: this step decides *which real object gets diagnosed*, and that
  needs to be explainable and testable, not a matter of model judgment.
- **Ambiguity handling**: multiple fuzzy matches for one mention are
  tie-broken by health, reusing spec 005's exact rule (`_pod_unhealthy`/
  `_deployment_unhealthy`, promoted to a shared helper rather than
  duplicated). If health doesn't disambiguate, the mention comes back
  `ambiguous` with its candidates listed -- never a silent pick, same
  principle as spec 005's same-name Pod/Deployment collision.
- Per-mention response: each resolved mention starts a normal diagnosis
  job via the *existing* internal path `POST /diagnose` already uses
  (extracted into a small shared helper, not duplicated) -- so `GET
  /diagnose/{job_id}` works identically afterward, no new polling
  mechanism.
- Cross-namespace read access for candidate listing (`list` on
  `deployments` across namespaces the ServiceAccount can see) -- still
  read-only, but broader than spec 001's single-namespace scope. See
  constitution v1.4.0.

**Out (deferred):**
- Matching against bare Pods (not owned by a Deployment) by fuzzy name --
  v1 only fuzzy-matches Deployment names. Pod name suffixes are
  randomly-generated and match poorly against a service mention like
  "payment" anyway; a caller who needs a specific bare Pod still has exact
  `POST /diagnose` with `kind: "Pod"`.
- Any LLM involvement in *choosing* between multiple candidate objects --
  ruled out, not just deferred (see Scope's reasoning on the Classifier
  precedent).
- Conversational follow-up ("no, the other one") -- an `ambiguous` result
  requires the caller to retry via plain `POST /diagnose` with an explicit
  `namespace`/`name`; there's no multi-turn state here.
- A UI for this -- this spec is the API surface only.

## Constitution check

- **Propose-only by default:** Still one explicit, authenticated HTTP call
  per report. Decomposition and fuzzy matching don't touch cluster state;
  they only decide *what* to diagnose, same as `resolve_intake()` already
  does for the exact-match path.
- **Read-only RBAC:** Broader than before (cross-namespace `list` on
  Deployments, not just one namespace) but still only `get`/`list`/`watch`
  -- no verb principle 2 didn't already allow. Called out explicitly in
  the v1.4.0 amendment rather than assumed.
- **Local-first, no external LLM calls:** Decomposition reuses
  `agent.llm.get_llm()` -- the same local `llama3.1:8b`, no new model, no
  new external call.
- **Every diagnosis is explainable:** The one part of this spec that
  *decides* which real object gets diagnosed (fuzzy matching + tie-break)
  is deterministic and inspectable, not an LLM judgment call -- a
  resolved mention can always be traced back to "this name matched, and
  health broke the tie" rather than "the model picked."
- **Full audit trail:** The decomposition result (mentions extracted) and
  every mention's resolution outcome (resolved/ambiguous/not_found) are
  logged, same convention as every other module in this codebase.

## Design

**Request/response schemas** (`api/schemas.py`):
```
QueryRequest:
  query: str

MentionResult:
  mentioned_service: str
  notes: str | None
  status: Literal["resolved", "ambiguous", "not_found"]
  job_id: str | None              # set only when status == "resolved"
  resolved_object: ObjectRef | None
  candidates: list[ObjectRef] | None   # set only when status == "ambiguous"

QueryResponse:
  mentions: list[MentionResult]
```
Always `200` -- a query that resolves zero of its mentions still returns a
normal response body; there's nothing to 4xx about, since the request
itself was well-formed.

**Decomposition** (`nlintake/decompose.py`):
```
DetectedMention:
  mentioned_service: str
  notes: str | None

decompose_query(query: str) -> list[DetectedMention]
```
Structured-output call, `get_llm().with_structured_output(list[DetectedMention])`
(or a wrapper model holding the list, matching whatever LangChain's
structured-output binding needs for a bare list). Always returns at least
one mention -- a query with no clearly extractable service name still
gets one entry (`mentioned_service` = best-effort guess, `notes` = the
full original query), so the pipeline still attempts resolution and
reports `not_found` rather than silently doing nothing.

**Fuzzy resolution** (`nlintake/fuzzy_resolve.py`):
```
fuzzy_candidates(mention: str, namespace_scope: list[str] | None = None) -> list[ObjectRef]
```
1. List Deployments across the target namespaces (all accessible if
   `namespace_scope` is `None`).
2. Case-insensitive substring match first (`mention.lower() in
   name.lower()`); if that yields nothing, fall back to
   `difflib.get_close_matches` against all Deployment names.
3. Return the matched `ObjectRef`s (kind always `"Deployment"` for v1).

```
resolve_mention(mention: DetectedMention) -> MentionResult
```
- 0 candidates -> `not_found`.
- 1 candidate -> call the *existing* `resolve_intake()` with that
  namespace/name (re-running spec 005's own health/existence checks, not
  bypassing them) -> start a job via the shared job-creation helper ->
  `resolved`.
- 2+ candidates -> apply the health tie-break (shared helper promoted out
  of `intake/resolve.py`): exactly one unhealthy -> resolve to it,
  same as above. Otherwise -> `ambiguous`, candidates listed as-is.

**API route** (`api/app.py`): `POST /diagnose/query` calls
`decompose_query()`, then `resolve_mention()` per detected mention,
collects the `MentionResult`s, returns `QueryResponse`. Same
`require_bearer_token` dependency as every other route.

## Acceptance criteria

- A single-target query ("my payment service is down") produces one
  `MentionResult` with `status: "resolved"` and a valid `job_id`, when
  exactly one Deployment name matches.
- A compound query naming two distinct services produces two
  `MentionResult`s, each resolved independently -- one mention failing to
  resolve doesn't block the other from starting its job.
- A mention matching zero Deployment names returns `not_found`, not an
  error response for the whole request.
- A mention matching multiple Deployments, where exactly one is unhealthy,
  resolves to that one (same health-tie-break behavior as spec 005's
  same-name collision case, applied here to fuzzy-matched candidates).
- A mention matching multiple Deployments where health doesn't
  disambiguate (all healthy or all unhealthy) returns `ambiguous` with
  every candidate listed, and does **not** start any job for that mention.
- `GET /diagnose/{job_id}` for a job started via `/diagnose/query` behaves
  identically to one started via `/diagnose` -- same schema, same polling.
- Unit tests cover `fuzzy_candidates()` directly (deterministic, no live
  cluster or LLM needed) and `decompose_query()` (mocked LLM).
- An integration test (`integration` + `requires_ollama`) runs a real
  free-text query against a live fixture and confirms it resolves to the
  correct object and produces a normal completed diagnosis.

## Open questions

- **Deployment-only fuzzy matching:** acceptable for v1 (see Scope), but
  means a report naming a bare Pod by a name fragment will never resolve
  via this endpoint. Worth revisiting if that turns out to matter in
  practice.
- **Namespace scope for "all accessible namespaces":** this spec assumes
  the ServiceAccount can list Deployments cluster-wide. Exact
  ClusterRole/RoleBinding manifest is deferred to implementation, same
  pattern as spec 001 and 005 left their RBAC manifests for later.
- **Fuzzy-match threshold tuning:** `difflib.get_close_matches`' default
  cutoff (0.6) is a starting guess, not a validated value -- likely needs
  adjustment once real service-name patterns (multi-word, hyphenated,
  abbreviated) are tested against it.
- **Rate/cost of listing Deployments cluster-wide per query:** fine at low
  request volume; if this endpoint sees real traffic, caching the
  candidate list for a short TTL is a reasonable future optimization, not
  built here.
