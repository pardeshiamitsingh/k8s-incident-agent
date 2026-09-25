# Spec: Hybrid retrieval

**Status:** draft
**Constitution version this spec complies with:** 1.8.0

## Problem

Retrieval is dense-only, and its query is just the failure-class name
(`retrieve_node` calls `retrieve_runbooks("CrashLoopBackOff", k=3)`). Two
problems follow. First, the app-specific runbooks (spec 011) compete with the
generic ones for the same three slots per class: for `CrashLoopBackOff`,
adding a new runbook already displaced `ecommerce-orders-db-auth` from the top
3. Second, a one-word query gives an embedding model very little to
discriminate on, so ordering among runbooks of the same class is close to
arbitrary. The evidence has far more signal (`password authentication failed
for user "shop"`) but is never used for retrieval. This spec adds lexical (BM25)
candidates alongside dense ones, a local cross-encoder reranker, and evidence-
aware queries.

## Scope

**In:**
- Hybrid retrieval in `knowledge_base/retrieve.py`: dense and BM25 candidates
  fused with reciprocal-rank fusion, then reranked by a local cross-encoder.
- Evidence-aware query construction in `agent/retrieve_node.py`.
- Env flag `INCIDENT_AGENT_RETRIEVAL_MODE=dense|hybrid`; `dense` reproduces
  today's behaviour exactly, including the class-only query.
- A retrieval evaluation (`evals/retrieval_check.py`) over the golden cases plus
  new golden cases recorded from the ecommerce demo scenarios, used as the gate
  for making `hybrid` the default.
- A setup command that fetches the reranker model once.

**Out:**
- Changing embeddings, chunking or the Chroma schema.
- Metadata pre-filtering by failure class.
- An LLM-based reranker, and learned or fine-tuned rankers.
- Changing the number of chunks per class (`CHUNKS_PER_FAILURE_CLASS` stays 3).
- Query rewriting by an LLM.

## Constitution check

- Propose-only by default: complies. Retrieval is read-only.
- Read-only RBAC: complies. No cluster access added.
- Local-first, no external LLM calls: complies. BM25 and the FlashRank model run
  in-process on CPU. The model weights are downloaded once at setup, like pulling
  an Ollama model; no query, evidence or runbook text leaves the machine at
  runtime.
- Every diagnosis is explainable: complies. Retrieved chunk IDs are still cited;
  the rerank score is logged, not hidden.
- Full audit trail: unchanged; postmortem chunks are part of the corpus and are
  retrievable by both paths.

## Design

**Retriever** (`retrieve_runbooks(query, k)`, signature unchanged):
- `dense` mode: exactly today's code path.
- `hybrid` mode: fetch the whole collection with `vector_store.get()`, build a
  `BM25Retriever` (top 10) over those documents, build the dense retriever (top
  10), combine with LangChain's `EnsembleRetriever` (reciprocal-rank fusion,
  equal weights), and rerank with `FlashrankRerank` to `k`. Results map to
  `RunbookChunk` as today.
- The BM25 index is rebuilt per call from Chroma's current contents. The corpus is
  about 50 chunks, so this costs milliseconds and avoids a stale in-process index
  (the same class of bug as spec 004's cross-process stale read: a postmortem
  written by the API process must be visible to a worker's next query).
- The FlashRank `Ranker` is constructed once per process and cached, since
  loading the model is the only expensive step.
- Chunk `id` must survive the round trip: documents built from `get()` carry
  their Chroma ids so `RunbookChunk.id` (and therefore citation validation) is
  identical across modes.

**Reranker model.** `INCIDENT_AGENT_RERANK_MODEL` (default a small FlashRank
model such as `ms-marco-MiniLM-L-12-v2`) and a cache dir under the repo's
gitignored `.cache/`. `python -m knowledge_base.fetch_reranker` downloads it once.
If the model is missing at runtime in `hybrid` mode, log a warning and return the
fused (unreranked) order rather than failing the diagnosis.

**Query construction** (`retrieve_node`). In `dense` mode the query stays the class
name. In `hybrid` mode it is `"<class>: <snippets>"`, where snippets are the
reason and message of matching container states and events plus the tail of the
logs, whitespace-collapsed and truncated to about 600 characters, recursing into
owned pods. The same evidence snippet is used for every class of a multi-class
result, prefixed by that class; per-class evidence attribution is out of scope.
Because it is built from collected evidence, it inherits spec 013's redaction: no
PII or secret can enter the query, the BM25 corpus match or the trace.
`Unknown` classification keeps its existing raw-text query path.

**Evaluation** (`evals/retrieval_check.py`). For each golden case, run
`classify_node` then retrieval in the chosen mode against frozen evidence (no
cluster, no LLM) and score whether the case's expected runbook is in the top 3,
plus mean reciprocal rank. The expected runbook is a new optional
`GoldenCase.expected_runbook` (source file stem), defaulting to the case id, since
existing case ids match their runbook names. Seven new golden cases are recorded
from the live ecommerce scenarios with `expected_runbook` set to the matching
`ecommerce-*` runbook. Output is a dense-versus-hybrid table.

**Dependencies:** `rank-bm25`, `flashrank`, `langchain-community` (plus
`langchain-classic` if the installed LangChain splits `EnsembleRetriever` there).

## Acceptance criteria

- `dense` mode passes every existing retrieval and agent test unchanged.
- `hybrid` returns `RunbookChunk` objects with the same ids and fields as `dense`
  for the same chunks; a postmortem ingested by another process is retrievable
  on the next call without restarting anything.
- With the reranker model absent, `hybrid` logs a warning and still returns
  results.
- On the retrieval check, `hybrid` is at least as good as `dense` on top-3 hit
  rate over all golden cases, and strictly better on the ecommerce cases (for
  example `ecommerce-orders-db-auth` appears in the top 3 for the orders
  scenario). If this fails, `dense` stays the default and the finding is
  recorded here.
- Hybrid retrieval adds at most 300 ms p95 over dense on the dev machine,
  measured after the model is loaded.
- The full eval run (spec 006) with `hybrid` does not lower the classification
  or keyword-hit scores versus `dense`.
- A live `/diagnose/query` for the orders failure cites `ecommerce-orders-db-auth`
  under `hybrid`.

## Open questions

- **Fusion weights and candidate counts:** equal weights and 10 candidates each
  are defaults; tune only if the retrieval check shows a gap.
- **Log tail in the query:** logs can be noisy and long; the 600-character cap and
  the choice of tail versus head are guesses to check against the eval.
- **Small corpus:** with about 50 chunks, hybrid and rerank may yield only modest
  gains over dense; the eval decides, and an honest "no significant gain" result
  is a valid outcome.
- **Model download at setup:** a new setup step and a first-run failure mode; the
  runtime fallback covers it, but the README must document `fetch_reranker`.
- **`langchain-community` weight:** it pulls a large dependency tree for two
  classes; if that proves painful, BM25 can be a small in-repo implementation
  instead.
