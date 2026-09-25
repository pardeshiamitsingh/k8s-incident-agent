---
id: dependency-failure-cascade
failure_class: DependencyFailure
symptoms:
  - "a service crashes or stays NotReady and its logs show connection refused or could not translate host name for another in-cluster service"
  - "the failing service's own configuration is correct; the service it depends on has no ready endpoints"
  - "several services fail at once and share a common backend such as a database or cache"
---

## Diagnosis

DependencyFailure: the service you were asked about is a victim, and the real
fault is in something it depends on. Its own container is fine; it fails or
crashes because a dependency (database, cache, another API) is unreachable.
This often shows as a restart loop or a pod that never becomes Ready, so
treat the first failing service as a symptom, not the root cause. Trace it:

1. Read the failing service's logs for the target host or Service name in
   `connection refused`, `could not translate host name`, `no route to host`
   or `connection timed out`. That name points at the dependency.
2. Check the dependency's Service Endpoints. No ready addresses means its
   backing pods are down, not selected (see the selector mismatch runbook) or
   not Ready.
3. Examine the dependency's own pods: Pending (scheduling or an unbound
   volume claim), crash-looping, image pull errors or failing readiness
   probes each have their own runbook. Diagnose that failure, since it is the
   root cause.
4. Tell this apart from a credentials problem: a wrong password produces an
   authentication error in the client's log even though the dependency is up
   and has Endpoints. That is a configuration fault in the caller, not a
   cascade.
5. Look for a shared dependency: if several services fail together, the
   common backend is the likely root cause.

## Remediation

- Fix the dependency first; do not restart or scale the victim services.
  Once the dependency has ready Endpoints, callers normally recover on their
  own as they retry.
- If a victim is slow to recover after the dependency is back, delete its pod
  once to reset the retry timer, or wait for the next retry.
- Longer term, make callers wait for their dependencies with retries and a
  startup or readiness gate, so an outage of a backend shows as NotReady
  rather than repeated restarts.
