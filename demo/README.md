# Ecommerce demo

A seven-workload ecommerce app you can break on demand, then diagnose with the
agent (spec 011). Everything lives in namespace `ecommerce`.

```
frontend -> catalog, cart, orders        cart -> redis
orders -> postgres (PVC)                 payment (standalone stub)
```

Stub images only (nginx, http-echo, redis, postgres, stress). Each backend
checks its dependency at startup and logs a clear `FATAL` line if it can't
reach it.

## Prerequisites

- A local kind cluster and `kubectl` pointed at it
- `helm` (`brew install helm`), demo tooling only, not an agent dependency
- The agent stack running: Ollama, Redis, Chroma (server mode), the API and a
  worker (see the main README)

## 1. Load the runbooks into the knowledge base

```
uv run python -m knowledge_base.ingest
```

(Use the same `INCIDENT_AGENT_CHROMA_*` environment as your API and worker, so
they read the collection you just wrote.) This ingests the seven
`ecommerce-*.md` runbooks alongside the generic ones.

## 2. Deploy the healthy app

```
demo/heal.sh
kubectl get pods -n ecommerce      # all 1/1 Running
```

## 3. Break something

```
demo/break.sh --list               # scenarios, expected class, sample query
demo/break.sh oom-payment
```

| Scenario | What breaks | Expected class |
|---|---|---|
| `oom-payment` | payment working set exceeds its memory limit | OOMKilled |
| `bad-image-catalog` | catalog image tag does not exist | ImagePullBackOff |
| `missing-secret-cart` | cart references a Secret that is absent | CreateContainerConfigError |
| `unschedulable-frontend` | frontend requests 64 CPU cores | Pending |
| `bad-probe-frontend` | frontend readiness probe hits a 404 path | ProbeFailure |
| `bad-db-password-orders` | orders uses the wrong Postgres password | CrashLoopBackOff |
| `pvc-unbound-postgres` | postgres claim uses a missing storageClass | Pending (see note) |

Scenarios accumulate; run `demo/heal.sh` to reset all of them.

## 4. Diagnose

In the UI (`http://localhost:8006/ui/`) paste your API token and ask, for
example:

- `The payment service in ecommerce keeps getting killed`
- `The orders service in ecommerce keeps crashing`
- `The frontend in ecommerce is running but not receiving traffic`

Or with curl:

```
curl -s -X POST localhost:8006/diagnose/query \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"query": "The orders service in ecommerce keeps crashing"}'
```

then poll `GET /diagnose/{job_id}`. The response cites the evidence and the
`ecommerce-*` runbook chunk it used.

## 5. Heal

```
demo/heal.sh
```

Resets every toggle and waits for all workloads to be Ready. Neither script
deletes a namespace or a volume.

## Notes

- `pvc-unbound-postgres` swaps to a second claim rather than editing the first
  (a PVC's storageClass is immutable), so healing needs no deletion.
- Failure toggles are chart values under `failures.*`; see
  `demo/ecommerce/values.yaml`.
- For offline demos, preload the images into kind with `kind load docker-image`.
- The PVC scenario classifies as `Pending`, not `PVCBindingFailure`: the pod's
  `FailedScheduling` event is what the collectors see, and the claim's own
  event is not collected today. The runbook is keyed to `Pending` so it is
  retrieved; the diagnosis still names the unbound claim from the event text.
