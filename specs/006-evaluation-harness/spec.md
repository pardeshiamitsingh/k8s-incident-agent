# Spec: Evaluation harness

**Status:** draft
**Constitution version this spec complies with:** 1.3.0

## Problem

Every phase so far has been validated against the same 4 hand-picked live
fixtures (spec 001). That's proven the pipeline *works*, but not whether
its diagnoses are actually *good*, and there's no way to tell if a future
prompt or model change makes things better or worse. Constitution Phase 6
calls for a golden set of 15-20 known incidents, scored for root-cause
accuracy, remediation quality, and latency -- this spec builds that.

## Scope

**In:**
- `evals/golden/*.json` -- one file per case: frozen `IncidentEvidence`
  (spec 001's model) plus the expected outcome for that evidence.
- A way to run the agent's classify->retrieve->diagnose->plan sequence
  against *frozen* evidence, skipping the live `collect` step entirely --
  eval runs must be fast and not depend on a live cluster or image pulls
  for every run.
- Scoring across the three constitution-named dimensions:
  - **Classification accuracy** (deterministic): does
    `classified_failure_classes` match the case's expected set exactly?
  - **Root-cause / remediation quality** (keyword-based, deterministic):
    what fraction of the case's expected keywords/themes appear in
    `diagnosis.root_cause` / `remediation_plan.steps`?
  - **Root-cause / remediation quality** (LLM-as-judge, complementary to
    keyword scoring, not a replacement): a local Ollama call rates how
    well the diagnosis/plan matches the case's expected outcome, 1-5 with
    a short rationale. Opt-in via a runner flag (see Design) -- keyword
    scoring alone can under-score a correct-but-differently-phrased
    diagnosis; LLM-judge alone is non-deterministic and self-referential
    (same family of model judging itself), so both run side by side,
    reported separately, never blended into one number.
  - **Latency**: wall-clock time for the classify->plan sequence per case
    (excludes collection, since that's skipped; excludes the judge call
    when `--llm-judge` is used, so latency stays comparable across runs
    with and without it).
- A runner that scores every golden case and prints a report (per-case
  pass/fail per dimension, aggregate accuracy, mean/p95 latency).
- A generator script that runs spec 001's `collect_evidence()` against a
  live fixture once and freezes the result as a golden case file -- so
  golden cases for the 4 fixtures spec 001 already has are *real*
  evidence, not hand-authored, and re-generating one is a single command
  when a fixture's expected symptoms change.

**Out (deferred):**
- Live-cluster-derived golden cases for failure classes with no existing
  fixture (e.g. `DNSResolutionFailure`, `NodePressureEviction`,
  `StuckTerminating`, `AppRBACDenied`) -- reproducing these in a local
  kind cluster is disproportionate effort for a v1 harness (see Open
  questions for how those cases get built instead).
- CI wiring / automatic regression gating -- this spec produces a report
  a human reads; deciding a numeric pass/fail threshold that blocks a
  merge is a future refinement once there's a baseline to compare against.
- Scoring spec 007's HTTP layer -- the harness evaluates the agent graph
  directly (classify->plan), not through the API; the API is a thin
  transport around the same graph, already covered by its own live test.

## Constitution check

- **Propose-only by default:** The harness only ever reads golden case
  files and runs the agent's reasoning nodes -- no K8s write access, no
  cluster access at all for most runs (only the one-time generator script
  touches a live cluster, and only to read).
- **Read-only RBAC:** Not applicable to the scoring run itself; the
  generator script reuses spec 001's existing read-only client.
- **Local-first, no external LLM calls:** Diagnose/Plan still run through
  the same local Ollama-backed nodes as spec 003 -- this spec adds no new
  model calls beyond what already exists, just runs them against frozen
  input instead of live-collected input. The optional LLM-judge call
  (`--llm-judge`) reuses the same local `agent.llm.get_llm()` -- no
  external model, no new principle-3 exception needed.
- **Every diagnosis is explainable:** Scoring itself doesn't touch
  citations directly, but a case with empty `cited_evidence`/
  `cited_runbook_chunks` would already have failed spec 003's schema
  validation before scoring ever runs -- this spec inherits that
  guarantee rather than re-implementing it.
- **Full audit trail:** Every eval run's full report (per-case scores,
  raw diagnosis/plan text, latency) is logged, so a specific run can be
  referenced later when comparing "did this get better after the prompt
  change."

## Design

**Golden case schema** (`evals/models.py`):
```
GoldenCase:
  id: str
  evidence: IncidentEvidence          # spec 001's model, frozen
  expected_failure_classes: list[str]
  root_cause_keywords: list[str]      # e.g. ["memory", "OOM", "limit"]
  remediation_keywords: list[str]     # e.g. ["memory limit", "resources.limits"]
```

**Running against frozen evidence** (`evals/run_from_evidence.py`): a
`run_agent_from_evidence(evidence, notes=None) -> AgentState` that calls
`classify_node` -> `retrieve_node` -> `diagnose_node` -> `plan_node`
directly in sequence (not through `agent.graph`'s compiled `StateGraph`,
which always starts at `collect`) -- the four functions are already plain,
independently-callable functions, so this needs no new graph definition,
just the same sequence spec 003's graph already encodes, entered one node
later.

**Scoring** (`evals/scoring.py`):
```
CaseResult:
  case_id: str
  classification_correct: bool        # exact set match
  root_cause_keyword_hits: float      # fraction of root_cause_keywords found
  remediation_keyword_hits: float     # fraction of remediation_keywords found
  llm_judge_score: int | None         # 1-5, only set when --llm-judge is used
  llm_judge_rationale: str | None
  latency_seconds: float
  diagnosis: Diagnosis
  remediation_plan: RemediationPlan
```
Keyword matching is case-insensitive substring search against the actual
`root_cause` / joined `steps` text -- crude but deterministic and legible;
a human reading a low-scoring case can see exactly which keyword was
missing and judge for themselves whether the diagnosis was actually wrong
or just phrased differently.

**LLM-as-judge** (`evals/judge.py`): reuses `agent.llm.get_llm()` (same
local model, no new dependency) with structured output:
```
JudgeVerdict:
  score: int          # 1-5
  rationale: str       # one or two sentences
```
Prompted with the case's `expected_failure_classes`,
`root_cause_keywords`, and `remediation_keywords` as the description of
what a good answer covers, plus the actual `diagnosis.root_cause` and
`remediation_plan.steps` -- asked to rate how well the actual answer
matches the expected concepts, not to re-derive the diagnosis itself.
Only invoked when the runner is passed `--llm-judge`; skipped by default
so a quick keyword-only pass over all 15-20 cases stays fast.

**Runner** (`evals/runner.py`): loads every `evals/golden/*.json`, runs
each through `run_agent_from_evidence`, scores it (plus the judge call if
`--llm-judge` was passed), and prints a report: per-case results (both
scoring signals shown side by side, never merged) plus aggregates
(classification accuracy %, mean keyword-hit rate, mean judge score if
used, mean/p95 latency). Exits non-zero if classification accuracy drops
below a configurable threshold (default: report only, no enforced gate --
see Out-of-scope on CI wiring).

**Generator** (`evals/generate_golden_case.py`): given a namespace + name
already exhibiting a known failure (i.e. a fixture applied and settled),
calls `collect_evidence()` once, writes the result plus
hand-specified `expected_failure_classes`/keywords to
`evals/golden/<id>.json`. This is how the 4 spec-001-backed cases get
built; the remaining cases (see Open questions) are hand-authored `.json`
files following the same schema, without needing a live run.

## Acceptance criteria

- `evals/golden/` contains cases for all 12 of spec 002's runbook failure
  classes, plus at least one `Unknown`-classification case (evidence with
  no reason the classifier's table recognizes) and one multi-failure-class
  Deployment case -- reaching the constitution's 15-20 target.
- The 4 cases corresponding to spec 001's existing live fixtures are
  generated from real `collect_evidence()` output (via the generator
  script), not hand-authored.
- Running the harness against the full golden set completes without
  requiring a live cluster or Ollama embedding calls for any case except
  regenerating the 4 live-derived ones.
- The report clearly shows, per case: classification correct or not, both
  keyword-hit fractions, latency, and the actual diagnosis/plan text (so a
  human can judge a low score without re-running anything).
- Deliberately breaking the Classify node's lookup table (e.g. removing
  the `OOMKilled` mapping) measurably drops classification accuracy in the
  report -- proves the harness actually detects a real regression, not
  just that it runs without erroring.
- With `--llm-judge`, every case's report includes a 1-5 `llm_judge_score`
  and `llm_judge_rationale` from the local model, shown alongside (not
  merged into) the keyword-hit fractions. Without the flag, both fields
  are absent/null and no extra LLM call happens.

## Open questions

- **How do the 8 classes with no live fixture get their golden evidence?**
  Hand-authored synthetic `IncidentEvidence` JSON, written to look like
  what `collect_evidence()` would plausibly produce for that failure
  class (e.g. a `DNSResolutionFailure` case with `describe.phase=Running`
  but log text containing a DNS error). Needs care to stay realistic --
  worth a second pass/review once drafted, since a synthetic case that
  doesn't actually resemble real evidence would validate nothing.
- **Keyword list authorship:** who decides what counts as a "required"
  keyword for a given case, and how strict (e.g. does "OOM" count as
  hitting "OOMKilled")? Proposed: case-insensitive substring, keywords
  chosen loosely (multiple synonyms/phrasings per concept) so the score
  reflects genuine miss vs. just different wording -- but this is a
  judgment call worth a second look once real scores come back low or
  high in ways that look wrong.
- **Latency baseline:** this spec measures latency but doesn't set a
  target (the constitution doesn't name one either). Worth establishing
  once a full 15-20-case run's actual numbers exist, not guessed upfront.
- **Regenerating live-derived cases over time:** cluster/fixture behavior
  could drift (e.g. a different K8s version changes an event message
  wording) -- there's no automatic staleness detection for the 4
  generated cases; re-running the generator is a manual, occasional
  action for now.
