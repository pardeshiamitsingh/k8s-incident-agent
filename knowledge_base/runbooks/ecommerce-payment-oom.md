---
id: ecommerce-payment-oom
failure_class: OOMKilled
symptoms:
  - "ecommerce payment pod restarting, last state terminated reason OOMKilled, exit code 137"
  - "payment deployment memory limit 64Mi exceeded by its working set"
---

## Diagnosis

In the ecommerce demo, `payment` (namespace `ecommerce`) runs a steady
working set of roughly 20M under a 64Mi memory limit. If its container shows
`terminated.reason == OOMKilled` and the restart count is climbing, the
working set has grown past the 64Mi limit. Check the `payment` Deployment's
container args (`--vm-bytes`) and `resources.limits.memory`: a working set
far above the limit (for example 200M against 64Mi) means a regression in
what the service allocates, not an undersized limit.

## Remediation

- Confirm the recent change: `helm history ecommerce -n ecommerce` and the
  chart value `failures.oomPayment`. If a recent release raised the working
  set, roll back with `helm rollback ecommerce <revision> -n ecommerce`.
- If the higher working set is intended, raise `payment` memory limit and
  request together (for example to 256Mi/128Mi) in the chart, then upgrade.
- Do not remove the memory limit; an unbounded payment pod can starve
  neighbours on the node.
