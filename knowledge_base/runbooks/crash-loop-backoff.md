---
id: crash-loop-backoff
failure_class: CrashLoopBackOff
symptoms:
  - "container state.waiting.reason == CrashLoopBackOff"
  - "restart_count climbing steadily"
  - "container briefly reaches Running, then Terminated, repeatedly"
---

## Diagnosis

`CrashLoopBackOff` means the container starts, exits, and Kubernetes keeps
retrying with exponential backoff. It is a symptom, not a root cause -- the
actual cause is why the container's process exited. Check, in order:

1. `describe.container_statuses[*].last_state.terminated.exit_code` and
   `.reason`. A non-zero exit code with `reason: Error` usually means the
   application crashed on startup (bad config, missing dependency, unhandled
   exception at boot).
2. `logs.previous` for the container -- this is the output from the run
   that just crashed, and is almost always more useful than `logs.current`
   (which may just show the *next* crash starting).
3. Whether the crash happens immediately (config/startup error) or after a
   delay (e.g. crashes on first real request, or hits a timeout connecting
   to a dependency).
4. Recent events for `Killing`/`BackOff` reasons confirming the restart
   pattern and its cadence.

## Remediation

- If `logs.previous` shows an application-level stack trace or fatal
  config error: fix the underlying application bug or configuration and
  redeploy. This is not something the agent can safely auto-fix.
- If the crash is caused by a missing dependency (e.g. a database the app
  can't reach at startup), verify that dependency is actually up and that
  the container's environment points at the right address.
- If the container exits immediately with no logs at all, check the image's
  entrypoint/command -- a typo'd command produces this with an empty log.
- Do not just increase `restartPolicy` backoff limits or add liveness probe
  slack as a substitute for fixing the crash -- that hides the symptom
  without addressing the cause.
