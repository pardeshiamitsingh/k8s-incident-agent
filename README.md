# k8s-incident-agent

Local, RAG-backed AI agent that diagnoses Kubernetes incidents and proposes
remediation plans. Built with LangChain, LangGraph, and Ollama.

## Workflow: spec-driven development

This project is developed spec-first:

1. **`memory/constitution.md`** — the fixed mission, principles, tech stack,
   and roadmap. Read this before writing any spec or code. Changing it
   requires an explicit amendment, not a silent edit.
2. **`specs/NNN-feature-name/spec.md`** — one spec per roadmap phase or
   feature, written from `specs/TEMPLATE.md`. Each spec must pass the
   "Constitution check" section before implementation starts.
3. Implementation follows the spec. If reality diverges from the spec during
   implementation, the spec gets updated first — code doesn't silently drift
   from what was agreed.

## Getting started

Roadmap phases are defined in `memory/constitution.md` §4. The next step is
writing `specs/001-collectors/spec.md` for Phase 1 (K8s event/log/describe
collectors) — see the template in `specs/TEMPLATE.md`.
