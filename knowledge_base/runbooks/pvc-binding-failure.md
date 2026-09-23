---
id: pvc-binding-failure
failure_class: PVCBindingFailure
symptoms:
  - "pod stuck Pending with a FailedScheduling or FailedMount event referencing a PVC"
  - "PersistentVolumeClaim status.phase stays Pending, never Bound"
  - "event reason ProvisioningFailed or WaitForFirstConsumer stuck"
---

## Diagnosis

A pod referencing a `PersistentVolumeClaim` that never binds will itself
stay `Pending` (or `ContainerCreating` if the PVC bound but the mount
itself fails). Check, in order:

1. `kubectl describe pvc <name>` events directly -- they carry the actual
   provisioning error, which the pod's own events won't show.
2. Whether the `StorageClass` referenced by the PVC actually exists and has
   a working provisioner. A typo'd or deleted `storageClassName` leaves the
   PVC permanently `Pending` with no further explanation.
3. `WaitForFirstConsumer` binding mode: some StorageClasses intentionally
   delay binding until a pod using the PVC is scheduled -- this is normal
   and not itself a failure, but it does mean the PVC's `Pending` state
   alone doesn't confirm a problem.
4. Zone/topology mismatch: for zonal storage, the volume may be
   provisionable only in a zone that has no available matching node
   capacity for the pod.
5. Quota: whether the underlying storage backend has hit a capacity or
   quota limit, surfaced as a `ProvisioningFailed` event with the
   provisioner's own error message.

## Remediation

- Typo'd/missing `storageClassName`: fix the PVC spec to reference a
  StorageClass that actually exists.
- Provisioner-side quota/capacity error: this is an infra-level issue --
  escalate to whoever owns the storage backend; not fixable by editing the
  pod or PVC spec alone.
- Zone mismatch: align the PVC's StorageClass topology (or the pod's node
  affinity) so a matching node and volume can coexist in the same zone.
- If the PVC is genuinely stuck (not just `WaitForFirstConsumer` waiting
  normally) and nothing else depends on its data, deleting and recreating
  it can clear a wedged provisioning attempt -- but never do this without
  confirming no data needs to be preserved first.
