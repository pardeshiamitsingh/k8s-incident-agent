---
name: spec
description: Create or update a spec for a feature, spec-driven style
---
1. Read `memory/constitution.md` (mission, principles, tech stack, roadmap)
   and the existing files under `specs/` — including `specs/TEMPLATE.md`,
   which every spec in this repo follows.
2. Ask clarifying questions using AskUserQuestion (max 3 rounds), then STOP
   and summarize the decisions before writing anything.
3. Write/update `specs/NNN-feature-name/spec.md` following
   `specs/TEMPLATE.md`'s structure exactly: Problem, Scope (In / Out),
   Constitution check (walk each Core Principle from `memory/constitution.md`
   §2 and state how this spec complies), Design, Acceptance criteria, Open
   questions.
4. If this introduces scope beyond what's already in `memory/constitution.md`
   §4's roadmap, or would require violating a Core Principle, propose a
   constitution amendment first (version bump + a dated entry under
   "Amendment history") rather than writing a spec that silently conflicts
   with it.
5. Print a "Status / Next step" block. Do not write implementation code.
