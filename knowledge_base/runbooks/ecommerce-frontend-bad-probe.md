---
id: ecommerce-frontend-bad-probe
failure_class: ProbeFailure
symptoms:
  - "ecommerce frontend pod Running but not Ready, event Unhealthy Readiness probe failed HTTP 404"
  - "frontend readiness probe path /healthz-missing returns 404"
---

## Diagnosis

The `frontend` (nginx) pod is `Running` with restarts at zero but its `Ready`
condition is `False`, and events show `Unhealthy: Readiness probe failed:
HTTP probe failed with statuscode: 404`. This is a readiness failure, not a
liveness one: the container is alive but is removed from the `frontend`
Service endpoints, so traffic stops reaching it. Read the probe's `httpGet.path`
and check that nginx actually serves it. The chart default is `/`; a path such
as `/healthz-missing` does not exist.

## Remediation

- Correct the readiness probe path to one the application serves, then
  upgrade. The pod becomes Ready and rejoins the Service.
- Do not loosen the probe just to make it pass; fix the path so the probe
  still reflects real health.
