# Spec: RAG knowledge base

**Status:** draft
**Constitution version this spec complies with:** 1.2.0

## Problem

Before the diagnoser (Phase 3) can propose a grounded remediation, it needs
a retrievable knowledge base of runbooks for common K8s failure classes it
can cite alongside collected evidence (spec 001). This is Phase 2 of the
roadmap: author runbook content and make it retrievable via local
embeddings, so a diagnosis can point at *which* runbook informed it
(constitution principle 4) rather than the LLM reasoning from evidence
alone with no grounding.

## Scope

**In:**
- 10-15 runbook markdown files, one per common failure class: at minimum
  the four spec 001's fixtures already exercise (`ImagePullBackOff`,
  `OOMKilled`, `CreateContainerConfigError`, `Pending`/unschedulable), the
  two more the constitution names explicitly (`CrashLoopBackOff`, PVC
  binding failures), plus enough additional common classes to reach the
  10-15 target (see Open questions for the proposed full list).
- A fixed runbook markdown structure (frontmatter + `##` sections) so
  ingestion and chunking are uniform across every file.
- Ingestion: markdown -> per-section chunks -> Ollama embeddings
  (`nomic-embed-text`, already pulled in Phase 0) -> a persistent Chroma
  collection.
- A retrieval function, `retrieve_runbooks(query, k) -> list[RunbookChunk]`,
  returning chunks plus their source file and section so later phases can
  cite exactly what they used.
- Manual retrieval-quality verification: a script that runs representative
  queries (one per major failure class) and prints top-k results for human
  review, per the constitution's "verify retrieval quality manually."

**Out (deferred to later specs):**
- Automatic re-ingestion or file-watching when runbook content changes --
  out of scope per principle 1 (no autonomous/continuous operation);
  ingestion is a one-shot script, run manually whenever content changes.
- Postmortem write-back of resolved incidents into the knowledge base
  (Phase 4) -- this spec only builds the retrieval capability, not what
  feeds it over time.
- Actual consumption of retrieved runbooks by a diagnoser LLM (Phase 3) --
  this spec stops at "retrieval works and returns citable chunks."
- Prometheus-informed or multi-cluster-specific runbook variants.

## Constitution check

- **Propose-only by default:** Retrieval is a pure read (query in, chunks
  out). Ingestion only writes to the local Chroma store; neither touches
  cluster state.
- **Read-only RBAC:** Not applicable -- this spec never talks to the K8s
  API.
- **Local-first, no external LLM calls:** Embeddings go exclusively through
  Ollama's `nomic-embed-text` model (verified running locally in Phase 0),
  wrapped via LangChain's `OllamaEmbeddings`; no external embedding API is
  called. Uses the constitution's named exception (v1.2.0): LangSmith
  tracing is enabled, so queries and retrieved chunk metadata are sent to
  LangChain's hosted LangSmith for observability -- this is the one
  permitted third-party call, opt-in via `LANGCHAIN_TRACING_V2` /
  `LANGCHAIN_API_KEY` env vars, not hardcoded or on-by-default in code.
- **Every diagnosis is explainable:** Every retrieved chunk carries its
  source runbook file and section heading, so a diagnosis can cite exactly
  which runbook section it drew from -- not just an opaque similarity
  score.
- **Full audit trail:** Retrieval calls (query, returned chunk IDs/sources,
  scores) should be logged the same way spec 001's collectors now are (see
  the logging-for-debuggability convention), since Phase 4's postmortem
  loop needs a record of what was retrieved for a given diagnosis.

## Design

**Runbook file structure** (`knowledge_base/runbooks/*.md`):
```
---
id: oom-killed
failure_class: OOMKilled
symptoms:
  - "container repeatedly restarts"
  - "describe shows state.terminated.reason == OOMKilled"
---

## Diagnosis
...

## Remediation
...
```

**Module layout** (new `knowledge_base/` package, alongside `collectors/`):
Built on LangChain's abstractions (constitution §3: "Framework | LangChain
| Tool wrappers, retrievers, output parsing") rather than calling `chromadb`
or `ollama` directly -- `OllamaEmbeddings` and the `Chroma` vector store
wrapper give the ingestion/retrieval code the same local-only guarantees
with a swappable interface Phase 3's LangGraph nodes can compose directly.
- `knowledge_base/runbooks/*.md` -- the authored content (10-15 files).
- `knowledge_base/models.py` -- `RunbookChunk`: `id`, `failure_class`,
  `section`, `text`, `source_file`.
- `knowledge_base/embeddings.py` -- `get_embeddings()` returning a
  `langchain_ollama.OllamaEmbeddings(model="nomic-embed-text")` instance.
- `knowledge_base/ingest.py` -- `ingest_runbooks()`: reads every file under
  `runbooks/`, chunks each by `##` section, and upserts into a
  `langchain_chroma.Chroma` vector store (persisted locally) via
  `add_documents`/`delete`, with metadata (`failure_class`, `source_file`,
  `section`) attached to each `Document`.
- `knowledge_base/retrieve.py` -- `retrieve_runbooks(query, k=5) ->
  list[RunbookChunk]`: uses the Chroma vector store's retriever interface,
  returns hydrated, similarity-ranked `RunbookChunk` objects.

**Chunking:** one chunk per `##` section within a runbook (`Diagnosis`,
`Remediation`, etc.) -- not the whole file as one chunk, and not further
sub-split. Keeps each chunk focused and matches how a diagnoser would want
to cite "the Remediation section of the OOMKilled runbook," not just "the
OOMKilled runbook" as an undifferentiated blob.

## Acceptance criteria

- 10-15 runbook markdown files exist under `knowledge_base/runbooks/`,
  each with valid frontmatter (`id`, `failure_class`, `symptoms`) and at
  least a `Diagnosis` and `Remediation` section.
- Every one of spec 001's four fixture failure classes has a corresponding
  runbook.
- `ingest_runbooks()` run against the authored runbooks populates the
  Chroma collection with one entry per section-chunk; embeddings are
  generated via Ollama only (no external network calls).
- `retrieve_runbooks("OOMKilled", k=3)` returns the `OOMKilled` runbook's
  chunks ranked above unrelated runbooks' chunks.
- `retrieve_runbooks("container image cannot be pulled", k=3)` returns the
  `ImagePullBackOff` runbook's chunks near the top -- demonstrating
  semantic, not just keyword, retrieval.
- Every returned `RunbookChunk` exposes `source_file` and `section`,
  sufficient for a future diagnoser to cite it.
- A manual verification run exists (script output or log) showing top-k
  results for at least 5 representative queries, one per major failure
  class, for human review of retrieval quality.

## Open questions

- ~~**Embedding model**~~ -- **Resolved:** `nomic-embed-text` (already
  pulled in Phase 0). Not benchmarking `mxbai-embed-large` for v1; revisit
  only if retrieval quality proves inadequate during manual verification.
- ~~**Full failure-class list**~~ -- **Resolved:** the 12 proposed classes,
  as-is: `CrashLoopBackOff`, `OOMKilled`, `ImagePullBackOff`,
  `Pending`/unschedulable, PVC binding failures, `CreateContainerConfigError`
  (missing ConfigMap/Secret), readiness/liveness probe failures, DNS
  resolution failures, node pressure/eviction, stuck `Terminating` pods,
  `ErrImageNeverPull`, insufficient RBAC for the *application's* own
  ServiceAccount (not the agent's).
- **Re-ingestion semantics:** re-running `ingest_runbooks()` after editing
  a runbook -- upsert by a deterministic chunk ID (derived from
  `source_file` + `section`) so stale chunks don't accumulate, or wipe and
  rebuild the whole collection each run? Leaning upsert-by-deterministic-ID,
  but a bug here would silently degrade retrieval quality over time
  without erroring, so worth confirming explicitly.
- **Chroma persistence path:** where the collection lives on disk and how
  it's created/managed -- same open question spec 001 left for fixture
  application (script vs. documented manual step), applies here for the
  `.chroma/` directory too.
