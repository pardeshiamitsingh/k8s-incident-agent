---
id: pending-unschedulable
failure_class: Pending
symptoms:
  - "describe.phase == Pending, pod stays Pending indefinitely"
  - "event reason FailedScheduling with the scheduler's reason in the message"
  - "no node assigned (spec.nodeName empty)"
---

## Diagnosis

A pod stuck `Pending` with a `FailedScheduling` event means the scheduler
could not find any node satisfying the pod's requirements. The event
message almost always states the exact reason -- read it first:

1. **Insufficient cpu/memory**: the message names the resource and how many
   nodes were rejected for it. Compare the pod's `resources.requests`
   against the largest available node's allocatable capacity.
2. **Node affinity/selector/taint mismatch**: the message says "didn't
   match Pod's node affinity/selector" or "had untolerated taint" -- the
   pod is asking for a node that either doesn't exist or that it isn't
   tolerating.
3. **Volume node affinity conflict**: a bound PVC is pinned to a zone/node
   the scheduler can't otherwise satisfy for this pod.
4. **No nodes at all** / cluster at capacity: every node is already full;
   this is a capacity problem, not a config problem.

## Remediation

- Oversized `resources.requests`: right-size the request to what the
  container actually needs, or add capacity (bigger/more nodes) if the
  request is genuinely justified.
- Affinity/selector/taint mismatch: fix the pod's `nodeSelector`/
  `affinity`/`tolerations` to match nodes that actually exist, or fix the
  node labels/taints if they were misconfigured.
- Volume affinity conflict: check the PV's `nodeAffinity` against where
  compute capacity actually exists; this usually means the PV was
  provisioned in the wrong zone.
- Cluster at capacity: scale the node pool, or free capacity by evicting
  lower-priority workloads -- not something to fix by changing this pod's
  spec alone.
