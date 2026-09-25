# Spec: Ecommerce demo environment

**Status:** implemented
**Constitution version this spec complies with:** 1.7.0

## Problem

The agent has only been exercised against single-deployment fixtures
(`fixtures/broken-deployments/`). A production-style demo needs a realistic
multi-service application to break, so the diagnosis flow (UI or API, natural
language query, runbook retrieval, remediation plan) can be shown end to end
against something that looks like a real system. This spec adds that
application, a way to inject failures on demand, and the knowledge-base
content that makes the diagnoses specific to it.

## Scope

**In:**
- A Helm chart at `demo/ecommerce/` deploying, into namespace `ecommerce`:
  `frontend`, `catalog`, `cart`, `orders`, `payment` (stateless services),
  plus `postgres` (Deployment + standalone PVC) and `redis`. Stub images only, no
  application code written for this project.
- Failure injection via chart values (`failures.<scenario>.enabled`) driven by
  `demo/break.sh <scenario>` and `demo/heal.sh`, plus `demo/break.sh --list`.
- Scenarios that produce failure classes the current classifier already
  recognises (see Design): OOMKilled, ImagePullBackOff,
  CreateContainerConfigError, Pending (unschedulable), ProbeFailure,
  CrashLoopBackOff (bad database password), and an unbound PVC (classified
  `Pending`, see Open questions).
- New runbooks under `knowledge_base/runbooks/` written for this app's
  topology (which service depends on what, where its config lives, what the
  fix looks like in this chart), ingested with the existing
  `ingest_runbooks()`.
- `demo/README.md`: install, break, diagnose (UI and curl), heal walkthrough,
  including sample "Describe the incident" queries per scenario.

**Out (later specs):**
- Cascading failure, Service selector mismatch and NetworkPolicy scenarios
  (spec 012, which needs new collectors and classifier rules).
- Real CRDs or an operator.
- Any change to the agent, API or UI. This spec adds only files under
  `demo/`, new runbooks, and tests.
- Load generation or metrics/Prometheus.

## Constitution check

- Propose-only by default: complies. The demo scripts mutate the *demo*
  namespace on the operator's request; the agent still only proposes.
- Read-only RBAC: complies. No agent RBAC change; the agent needs only the
  reads it already uses (Pods, Deployments, events, logs) in `ecommerce`.
- Local-first, no external LLM calls: complies. Images come from public
  registries at deploy time (a cluster concern, not agent data flow); no
  incident data leaves the machine. No new LLM calls.
- Every diagnosis is explainable: unchanged; new runbooks are chunked and
  cited like any other.
- Full audit trail: unchanged. A demo diagnosis can be confirmed via the
  existing postmortem endpoint, which writes back to the same store.

## Design

**Layout**
```
demo/
  ecommerce/            # Helm chart: Chart.yaml, values.yaml, templates/
  break.sh heal.sh
  README.md
knowledge_base/runbooks/ecommerce-*.md
tests/test_demo_chart.py
```

**Application topology.** `frontend` (nginx) -> `catalog`, `cart`, `orders`;
`orders` -> `postgres` and `payment`; `cart` -> `redis`. Each stateless
service is a small stub container (nginx, http-echo or a shell script) whose
startup checks its dependency and exits non-zero with a clear log line if it
cannot reach it, so dependency failures produce real, log-visible crashes
rather than silent success. Services get realistic labels (`app`, `tier`,
`part-of: ecommerce`), resource requests, probes and a ConfigMap/Secret each.

**Scenarios** (each toggled by a chart value; `heal.sh` restores defaults):

| Scenario | Injection | Expected class |
|---|---|---|
| `oom-payment` | payment memory limit far below its working set | OOMKilled |
| `bad-image-catalog` | catalog image tag that does not exist | ImagePullBackOff |
| `missing-secret-cart` | cart references a Secret that is absent | CreateContainerConfigError |
| `unschedulable-frontend` | frontend requests more CPU than any node has | Pending |
| `bad-probe-frontend` | frontend readiness probe points at a 404 path | ProbeFailure |
| `bad-db-password-orders` | orders gets a wrong Postgres password | CrashLoopBackOff |
| `pvc-unbound-postgres` | Postgres PVC uses a non-existent storageClass | Pending (see Open questions) |

**Scripts.** `break.sh <scenario>` runs `helm upgrade --reuse-values --set
failures.<scenario>.enabled=true`; `heal.sh` runs `helm upgrade` with
`failures` reset. Both refuse to act outside namespace `ecommerce` and print
the exact command they run. Neither deletes a namespace.

**Runbooks.** One runbook per scenario, `failure_class` set to the
classifier's class for it (retrieval is keyed on the classified class), using
the existing frontmatter format (`id`, `failure_class`, `symptoms`) and
`## Diagnosis` / `## Remediation` sections. Content names the real service,
Secret, ConfigMap and chart value involved, so a retrieved chunk lets the
planner give app-specific steps rather than generic ones.

## Acceptance criteria

- `helm lint demo/ecommerce` passes and `helm template` renders valid YAML
  for the default and each scenario (unit test, no cluster needed).
- `helm install` on the local kind cluster reaches all workloads Ready.
- For each scenario, `break.sh` produces the expected class per the table
  (checked by running `classify_evidence` on live evidence, and by a live
  `/diagnose` call for at least three scenarios), and `heal.sh` returns every
  workload to Ready.
- Each new runbook parses with the existing chunker, ingests without error,
  and is retrieved in the top-k when its class is queried (extend the
  spec 002 retrieval check).
- A natural-language query per scenario in the README resolves to the right
  Deployment via the UI or `/diagnose/query`.
- `demo/README.md` walkthrough works from a clean cluster as written.

## Open questions

- **Diagnosis quality with the local model:** classification is deterministic,
  but root-cause wording comes from the local LLM. Some scenarios may need
  runbook tuning after a live run; expect a follow-up commit, as in earlier
  phases.
- **Resource footprint:** seven workloads on a single-node kind cluster; the
  defaults must be small enough not to trip the `unschedulable` scenario by
  accident.
- **Image availability:** stub images require pulling from public registries;
  the README should say to preload them into kind for offline demos.
- **Postgres data:** a throwaway database with no persistence guarantees is
  fine for a demo, but `heal.sh` after `bad-db-password-orders` must not
  require deleting the PVC.
- **Helm as tooling:** Helm is demo-only and not an agent dependency; it is
  not installed by this project (`brew install helm`).
- **Resolved during live validation:** (1) Postgres is a Deployment plus
  standalone PVC, not a StatefulSet, so the PVC scenario can swap claims and
  heal without deletion (volumeClaimTemplates and storageClass are
  immutable); it also keeps Postgres inside the Deployment kinds the agent
  diagnoses. (2) An unbound-PVC pod surfaces as `FailedScheduling`, which the
  classifier maps to `Pending`; `PVCBindingFailure` only fires from mount and
  provisioning events the pod does not carry. Its runbook is keyed to
  `Pending`. Collecting the PVC's own events would be a collector change for a
  later spec. (3) Two scenarios also report a secondary `ProbeFailure`, which
  is accurate (the rollout's new pod is never Ready).
