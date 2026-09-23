---
id: stuck-terminating
failure_class: StuckTerminating
symptoms:
  - "pod status shows Terminating for far longer than terminationGracePeriodSeconds"
  - "kubectl delete does not remove the pod even after the grace period expires"
  - "pod stuck Terminating often has a finalizer listed in metadata.finalizers"
---

## Diagnosis

A pod stuck `Terminating` well past its grace period almost always means
something is blocking its actual removal -- check, in order:

1. `metadata.finalizers` on the pod -- a finalizer that's waiting on an
   external controller to acknowledge cleanup (and that controller is
   down, crashed, or was never running) will block deletion indefinitely.
   This is the single most common cause.
2. Whether the container process itself is ignoring `SIGTERM` and running
   past `terminationGracePeriodSeconds` -- the kubelet does eventually
   `SIGKILL`, but a container that traps/ignores signals, or a very long
   custom `preStop` hook, can extend this well beyond what looks normal.
3. Node-level issues: if the node itself is `NotReady`/unreachable, the
   kubelet that would actually terminate the container can't run its
   cleanup, and the pod object can be left in `Terminating` until the node
   comes back or the pod is force-deleted.
4. Whether this is one pod or a pattern across many pods on the same
   node/controller -- a pattern points at a systemic finalizer or
   controller bug, not a one-off.

## Remediation

- Stuck finalizer with a genuinely-dead controller: this needs a human
  decision -- either fix/restart the controller that owns the finalizer,
  or, only after confirming no real cleanup work is being skipped, remove
  the finalizer manually (`kubectl patch ... -p '{"metadata":{"finalizers":[]}}'
  --type=merge`) to unblock deletion. Never do this automatically or
  silently -- it can skip real cleanup (e.g. detaching a cloud volume).
- Container ignoring `SIGTERM`: fix the application/image to handle
  `SIGTERM` gracefully, or explicitly shorten
  `terminationGracePeriodSeconds` if the extra time isn't actually needed.
- Unreachable node: address the node's health directly; a pod stuck
  `Terminating` purely because its node is down will usually resolve once
  the node returns or is properly drained/removed from the cluster.
- Force-deleting a pod (`--grace-period=0 --force`) removes the API object
  immediately but does *not* guarantee the container process actually
  stopped -- only use it once the underlying cause is understood, not as a
  first response.
