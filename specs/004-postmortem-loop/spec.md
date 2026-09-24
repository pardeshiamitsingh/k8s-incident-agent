# Spec: Postmortem loop

**Status:** draft
**Constitution version this spec complies with:** 1.3.0

## Problem

Every diagnosis so far is a one-shot: the agent proposes, a human acts,
and whatever actually happened is lost. Constitution Phase 4 calls for
resolved incidents to be written back into the RAG store so the system
improves over time. This spec is the minimal version of that loop: a
human confirms what actually happened for a given job, and -- only when
the diagnosis was actually correct -- that becomes new, retrievable
context for future incidents. Deliberately small (see Open questions for
what's cut).

## Scope

**In:**
- `POST /diagnose/{job_id}/postmortem` (extends spec 007's API): body
  `{was_correct: bool, actual_root_cause: str, actual_fix: str}`.
- If `was_correct` is `true`: the postmortem is embedded and upserted into
  spec 002's *existing* Chroma collection (the same one the 12 runbooks
  live in) -- tagged so it's retrievable by the same failure-class query
  spec 003's `retrieve_node` already makes. **No changes to
  `retrieve_node` or any Phase 3 code** -- a postmortem is just another
  document in the collection it already queries.
- If `was_correct` is `false`: logged (audit trail), not ingested for
  retrieval -- a wrong conclusion never gets cited as if it were
  validated.
- Requires the referenced job to exist and have `status == "completed"`
  (a still-running or failed job has no diagnosis to confirm or correct
  against).
- Idempotent by design: resubmitting a postmortem for the same `job_id`
  upserts (deterministic chunk ID), doesn't duplicate or require separate
  "already submitted" bookkeeping.

**Out (deferred -- see the fuller design discussion this spec is the
trimmed version of):**
- A separate Chroma collection / provenance distinction between
  hand-authored runbooks and postmortems -- v1 tags via metadata
  (`source_file="postmortem-<job_id>-<failure_class>"`) within the same
  collection instead. Revisit if runbook vs. postmortem provenance needs
  to be visible/filterable later.
- Richer postmortem schema (confidence ratings, multiple contributors,
  structured remediation steps rather than free text).
- Any endpoint to list/browse postmortem history.
- Auto-feeding confirmed postmortems into Phase 6's golden eval set --
  a natural future source of real cases beyond the 15 hand-built ones,
  not built here.
- Any automatic/inferred postmortem trigger (e.g. noticing an object
  became healthy) -- ruled out, not just deferred: it would write
  unverified conclusions into the knowledge base, and continuous
  monitoring to notice "became healthy" conflicts with principle 1's
  on-demand-only constraint the same way an Alertmanager-triggered agent
  run already does.

## Constitution check

- **Propose-only by default:** This endpoint only ever reads a job and
  writes to the local vector store -- no K8s API call, no cluster
  mutation anywhere in this spec.
- **Read-only RBAC:** Not applicable -- no K8s access.
- **Local-first, no external LLM calls:** Reuses `knowledge_base`'s
  existing `OllamaEmbeddings`-backed vector store; no new model, no new
  external call.
- **Every diagnosis is explainable:** A postmortem-sourced chunk is
  *more* traceable than a hand-authored runbook, not less -- its
  `source_file` names the exact job it came from, so a future diagnosis
  citing it points at a specific real past incident, not just "some
  runbook."
- **Full audit trail:** Every submitted postmortem is logged, correct or
  not -- an incorrect diagnosis being confirmed-wrong is exactly the kind
  of outcome principle 5 says must be recorded, whether or not it changes
  the knowledge base.

## Design

**Request/response schemas** (`api/schemas.py`):
```
PostmortemRequest:
  was_correct: bool
  actual_root_cause: str
  actual_fix: str

PostmortemAccepted:
  ingested: bool   # mirrors was_correct -- lets the caller confirm
                    # whether this submission actually changed retrieval
```

**Ingestion** (new `knowledge_base/postmortem.py`, alongside `ingest.py`):
```
ingest_postmortem(
    job_id: str,
    resolved_object: ObjectRef,
    failure_classes: list[str],
    original_root_cause: str,
    actual_root_cause: str,
    actual_fix: str,
) -> None
```
Builds one document:
```
Incident: {kind} {namespace}/{name}
Original diagnosis: {original_root_cause}
Actual root cause: {actual_root_cause}
Actual fix applied: {actual_fix}
```
and upserts it into `knowledge_base.ingest.get_vector_store()` -- once per
entry in `failure_classes` (mirroring `retrieve_node`'s own per-class
handling for multi-failure-class Deployments), each with a deterministic
ID `postmortem-{job_id}-{failure_class}` and metadata
`{failure_class, section: "Postmortem", source_file: "postmortem-{job_id}-{failure_class}"}`.

**API route** (`api/app.py`):
1. `GET` the job from `api/jobs.py`'s `job_store`; `404` if unknown,
   `409` if `status != "completed"`.
2. Log the submission (job ID, `was_correct`) regardless of outcome.
3. If `was_correct`: call `ingest_postmortem()` with the job's own
   `resolved_object`, `classified_failure_classes`, and
   `diagnosis.root_cause` as `original_root_cause`, plus the request's
   `actual_root_cause`/`actual_fix`.
4. Return `PostmortemAccepted(ingested=request.was_correct)`.

No new authentication model -- reuses spec 007's existing bearer-token
`require_bearer_token` dependency unchanged.

## Acceptance criteria

- `POST /diagnose/{job_id}/postmortem` for an unknown `job_id` returns
  `404`.
- `POST /diagnose/{job_id}/postmortem` for a job that's still `running`
  returns `409`.
- Submitting with `was_correct: true` results in `retrieve_runbooks()`
  (spec 002, unchanged) being able to return the new postmortem chunk for
  a query matching its failure class -- proving no Phase 3 code needed
  to change for postmortems to become retrievable.
- Submitting with `was_correct: false` does not change what
  `retrieve_runbooks()` returns for that failure class, but is still
  logged.
- Resubmitting a postmortem for the same `job_id` updates the existing
  chunk (verified via the vector store's chunk count staying the same,
  not growing) rather than duplicating it.
- A multi-failure-class job's postmortem is retrievable under each of its
  failure classes independently, matching `retrieve_node`'s own
  per-class query behavior.
- An integration test (marked `integration` and `requires_ollama`) runs
  the full flow live: `POST /diagnose` against a fixture, submit a
  correct postmortem for the resulting job, then confirm
  `retrieve_runbooks()` surfaces it for that failure class.

## Open questions

- **Failed jobs:** a job that errored (`status == "failed"`) has no
  diagnosis to confirm or correct -- this spec rejects a postmortem for
  it (`409`), but there may be value in capturing "the agent itself
  broke on this incident" as its own kind of record. Deferred; today
  that's just visible in the job's `error` field and application logs.
- **Multiple postmortems disagreeing over time:** if a postmortem is
  submitted, then resubmitted later with a different `actual_root_cause`
  for the same `job_id`, the upsert silently replaces the earlier one --
  no history of the correction itself is kept. Acceptable for v1;
  revisit if postmortem authorship/revision ever needs its own audit
  trail beyond "the current version is upserted."
- **Quality control on `actual_root_cause`/`actual_fix` free text:**
  nothing validates that a human's submitted postmortem is itself
  accurate or well-written -- a bad postmortem pollutes retrieval just as
  surely as a bad runbook would. No different from how the 12 original
  runbooks were trusted when hand-authored; worth a human review norm,
  not enforceable in code for v1.
