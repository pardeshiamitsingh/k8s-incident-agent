---
id: ecommerce-postgres-pvc-unbound
failure_class: Pending
symptoms:
  - "ecommerce postgres pod Pending, PersistentVolumeClaim postgres-data-fast unbound, storageclass not found"
  - "event FailedScheduling: pod has unbound immediate PersistentVolumeClaims"
---

## Diagnosis

The `postgres` Deployment mounts a PVC. A pod that stays `Pending` with
`FailedScheduling` and a message about an unbound PersistentVolumeClaim means
the claim cannot bind. Inspect the claim the pod uses (`claimName` in the pod
spec): `postgres-data-fast` requests `storageClassName:
fast-ssd-does-not-exist`, a class that does not exist in this cluster (only
`standard` does), so no volume is ever provisioned. The healthy claim is
`postgres-data` with the default class. Because Postgres is down, `orders`
will also fail its startup check, which is a consequence, not a second cause.

## Remediation

- Point the Deployment back at a claim that can bind (`postgres-data`) or set
  the claim's storageClass to one that exists (`kubectl get storageclass`),
  then upgrade. A PVC's storageClass cannot be edited in place, so switch the
  claim rather than patching it.
- Once Postgres is Ready, dependent services such as `orders` recover on
  their own.
