---
id: probe-failure
failure_class: ProbeFailure
symptoms:
  - "event reason Unhealthy, message mentions Liveness or Readiness probe failed"
  - "readiness probe failing: pod Running but condition Ready == False, excluded from Service endpoints"
  - "liveness probe failing: container repeatedly restarted (state cycles through Running -> Terminated)"
---

## Diagnosis

Readiness and liveness probe failures look similar in events but have very
different consequences -- always identify which one first from the event
message and the specific consequence observed:

1. **Readiness probe failing**: the pod stays `Running` (no restart) but
   its `Ready` condition is `False`, and it's removed from any Service's
   endpoints. Traffic simply stops reaching it. This alone does not kill
   the container.
2. **Liveness probe failing**: the kubelet kills and restarts the
   container after repeated failures -- this looks like `CrashLoopBackOff`
   from the outside, but the trigger is the probe, not the app crashing on
   its own.
3. Read the probe's actual check (HTTP path/port, TCP port, or exec
   command) from the pod spec and try it manually against the container to
   see whether it's the app that's actually unhealthy, or the probe
   configuration itself is wrong (wrong port, wrong path, too-short
   timeout for a slow-starting app).
4. Check `initialDelaySeconds`/`timeoutSeconds`/`failureThreshold` against
   how long the app actually takes to become ready -- a probe that fires
   before the app has finished starting up is a very common false
   positive, especially right after deploy.

## Remediation

- Probe fires too early: increase `initialDelaySeconds` (or add a
  `startupProbe` for slow-starting apps) rather than disabling the probe.
- Probe checks the wrong endpoint/port: fix the probe configuration to
  match what the app actually serves.
- Probe is correct and the app genuinely isn't ready/healthy: this is an
  application-level issue (e.g. a dependency it waits on at startup, or
  a real runtime health regression) -- fix the app, not the probe.
- Never simply remove a failing liveness probe as a fix -- that trades a
  visible restart loop for an invisible hung/unresponsive container
  serving no traffic usefully.
