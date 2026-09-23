---
id: oom-killed
failure_class: OOMKilled
symptoms:
  - "container state.terminated.reason == OOMKilled"
  - "restart_count > 0, logs.previous non-empty"
  - "memory usage climbing toward the container's memory limit before the kill"
---

## Diagnosis

`OOMKilled` means the kernel's OOM killer terminated the container because
it exceeded its memory limit (`resources.limits.memory`). Confirm:

1. `describe.container_statuses[*].state.terminated.reason == "OOMKilled"`.
2. Compare the container's `resource_limits.memory` against what the
   application actually needs -- a limit that's simply too low for normal
   operation is the most common cause.
3. `logs.previous` right before the kill: does the app show signs of a
   memory leak (steadily growing heap, no plateau) or a single large spike
   (e.g. processing one oversized request/batch)?
4. Whether this is a first occurrence or a repeating pattern -- a repeating
   OOM kill on a fixed cadence often points at a leak; a one-off often
   points at a workload spike the limit wasn't sized for.

## Remediation

- If the limit is simply undersized for normal steady-state usage: raise
  `resources.limits.memory` (and `requests.memory` to match, so the
  scheduler places it on a node that can actually support it).
- If usage grows unboundedly over time with no plateau: this is a memory
  leak in the application, not a sizing problem -- raising the limit only
  delays the next kill. Needs an application-level fix.
- If the spike correlates with a specific operation (e.g. a large batch
  job), consider whether that operation should be resource-isolated
  (separate Job/pod) rather than sized into the main deployment's limit.
- Never remove the memory limit entirely as a fix -- an unbounded container
  can then starve or evict other pods on the same node.
