# Spec: Web frontend

**Status:** draft
**Constitution version this spec complies with:** 1.6.0

## Problem

The only interface today is the HTTP API (specs 007-009), which means an
engineer has to hand-craft `curl` calls, copy job IDs, and re-poll to see a
result. Phase 7 named a web UI as a possible future addition. This spec adds
the smallest useful one: type an incident in plain English, see the diagnosis
and remediation plan appear, without touching `curl`.

## Scope

**In:**
- A single-page UI: a token field, a free-text query box, and a results area.
- Submitting calls `POST /diagnose/query` (spec 008), then polls
  `GET /diagnose/{job_id}` (spec 007/009) for every mention with status
  `resolved`, until each job is `completed` or `failed`.
- Rendering per mention:
  - `resolved`: resolved object, classified failure classes, root cause,
    cited evidence, cited runbook chunks (with the retrieved chunk text
    available on expand), and remediation steps.
  - `ambiguous`: the candidate objects, with a note to rephrase the query.
  - `not_found`: a plain "no matching object" message.
  - `failed` job: the job's `error` string.
- Bearer-token auth: the user pastes the token; it is kept in
  `sessionStorage` and sent as `Authorization: Bearer ...`.
- Served as static files by the existing FastAPI app, mounted at `/ui`,
  same origin as the API.
- Vanilla HTML/CSS/JS, no build step, no third-party scripts or fonts.

**Out (push to later specs):**
- Postmortem submission form (`POST /diagnose/{id}/postmortem`).
- Clicking an ambiguous candidate to diagnose it directly (would call
  `POST /diagnose` with the chosen object; small follow-up).
- Job history / listing (no list endpoint exists).
- A separate frontend dev server, framework, or build tooling.
- TLS and real user accounts (deployment concern, as in Phase 7).

## Constitution check

- Propose-only by default: complies. The UI only displays proposed remediation
  steps; it has no button or call that executes anything.
- Read-only RBAC: complies. No new cluster access; the UI only talks to the
  existing API.
- Local-first, no external LLM calls: complies. No CDN scripts, fonts, or
  analytics; every asset is served from this app. No new LLM calls.
- Every diagnosis is explainable: complies, and surfaces it. The UI renders
  the diagnosis's cited evidence and cited runbook chunks rather than only
  the root-cause sentence.
- Full audit trail: unchanged. Diagnoses are already logged by the API and
  worker; the UI adds no path that bypasses that. Postmortem writeback from
  the UI is deferred, not removed (the API endpoint still exists).

## Design

**Files**
- `frontend/index.html`, `frontend/app.js`, `frontend/style.css`.
- `api/app.py`: mount `StaticFiles(directory="frontend", html=True)` at
  `/ui`. `/healthz` and the API routes are unchanged. The static mount is
  exempt from the bearer check (it serves no data); every API call the page
  makes carries the token, so the API's access control is untouched.

**Auth**
- The page prompts for the token once, stores it in `sessionStorage` (cleared
  when the tab closes; never `localStorage`, never in the URL), and attaches
  it to every `fetch`. A `401` response clears the stored token and re-shows
  the token field.

**Flow (`app.js`)**
1. `POST /diagnose/query` with `{query}`.
2. For each mention with `status == "resolved"`, poll
   `GET /diagnose/{job_id}` every 3s until `completed` or `failed`, with a
   client-side ceiling (default 5 minutes) after which the card shows
   "still running" and stops polling. Mentions poll independently, so a slow
   job does not block the others from rendering.
3. `429` from the API (spec 009 backpressure) is shown as "system busy, try
   again shortly" rather than a generic error.

**Rendering safety**
- All API-derived text (query echo, root cause, evidence, chunk text) is
  inserted with `textContent`, never `innerHTML`. Runbook and postmortem chunk
  text is user-authored and must be treated as untrusted.

**No backend contract changes.** The UI consumes `QueryResponse` and
`JobStatus` exactly as defined in `api/schemas.py`.

## Acceptance criteria

- `GET /ui/` returns the page with no auth header; `GET /diagnose/x` still
  returns 401 without one.
- With a valid token and the OOM fixture, typing "the service named
  oom-killed is broken" shows a completed diagnosis with a root cause, at
  least one cited runbook chunk, and remediation steps.
- A query resolving no objects shows the `not_found` message; an ambiguous
  one lists candidates; neither starts polling.
- A compound query with two mentions renders two independent cards.
- A `failed` job shows its error; a `429` shows the busy message.
- A wrong token yields a visible "invalid token" state and clears
  `sessionStorage`.
- Injecting `<img src=x onerror=...>` into a runbook chunk does not execute
  (verified by a test asserting `textContent` rendering, e.g. a small
  DOM-level test or a live browser check).
- Static mount test in `tests/test_api_app.py`: `/ui/` served without auth,
  API routes still auth-gated.
- No network requests leave the origin (checked in browser devtools during
  the live check).

## Open questions

- **Clickable ambiguous candidates:** cheap to add via `POST /diagnose`, but
  deferred to keep v1 minimal. Worth doing once the UI has real use?
- **Job lifetime:** jobs expire from Redis after 24h (spec 009), so a
  refreshed page cannot resume polling; the UI keeps no job history. Acceptable
  for v1, or persist job IDs in `sessionStorage`?
- **Polling vs. streaming:** 3s polling matches the existing API; server-sent
  events would need a backend change and are out of scope here.
- **Token on a shared machine:** `sessionStorage` limits exposure to the tab's
  lifetime, but any XSS in the page could read it; the `textContent` rule is
  the mitigation. Revisit if the UI ever renders rich content.
