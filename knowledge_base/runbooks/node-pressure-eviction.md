---
id: node-pressure-eviction
failure_class: NodePressureEviction
symptoms:
  - "pod status.phase == Failed, status.reason == Evicted"
  - "event reason Evicted, message mentions memory/disk/pid pressure"
  - "multiple unrelated pods on the same node evicted around the same time"
---

## Diagnosis

An `Evicted` pod was removed by the kubelet because the *node* it was on
came under resource pressure -- this is a node-level problem surfacing as
a pod-level symptom, not (usually) a bug in the evicted pod itself:

1. The eviction event's message states which pressure triggered it:
   `MemoryPressure`, `DiskPressure`, or `PIDPressure`.
2. Check whether *other, unrelated* pods on the same node were evicted
   around the same time -- if so, this strongly confirms a node-level
   resource exhaustion event rather than something specific to this
   workload.
3. For `DiskPressure`: check what's consuming disk on that node --
   commonly unbounded container log growth, orphaned images/volumes, or
   a workload writing large temp files to a node-local (not PVC-backed)
   path.
4. For `MemoryPressure`: check overall node memory allocation vs. actual
   usage -- pods without memory *limits* set can overcommit a node even
   when individual containers look fine in isolation.
5. Kubelet typically evicts lower-`QoS`-class pods first (`BestEffort`
   before `Burstable` before `Guaranteed`) -- a `BestEffort` pod (no
   requests/limits set) being evicted while `Guaranteed` pods survive is
   expected behavior, not a bug.

## Remediation

- Set (or right-size) `resources.requests`/`limits` on pods that were
  running with no limits -- unbounded pods are both more likely to cause
  pressure and more likely to be evicted first.
- Node-level disk pressure from log growth: ensure container log rotation
  is configured; investigate the specific workload writing excessive
  node-local disk data.
- Chronic pressure on a node pool: this is a capacity problem -- add nodes
  or rebalance workloads, not something fixable by editing one pod's spec.
- Evicted pods are simply rescheduled by their controller (Deployment/
  ReplicaSet) automatically -- if a pod was evicted and never came back,
  investigate separately as a scheduling failure (see the
  Pending/unschedulable runbook), not as a continuation of the eviction
  itself.
