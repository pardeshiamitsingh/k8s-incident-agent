---
id: ecommerce-frontend-unschedulable
failure_class: Pending
symptoms:
  - "ecommerce frontend pod Pending, event FailedScheduling Insufficient cpu"
  - "frontend requests 64 CPU cores, more than any node offers"
---

## Diagnosis

A `frontend` pod stuck in `Pending` with a `FailedScheduling` event
(`0/1 nodes are available: Insufficient cpu`) means the scheduler cannot
place it. Read the pod's `resources.requests.cpu` and compare it to node
allocatable CPU (`kubectl describe node`). A request of `64` cores on a
laptop-sized kind node can never fit; the normal request is `20m`. Nothing is
wrong with the node; the request is unreasonable.

## Remediation

- Lower the frontend CPU request to a realistic value (the chart default is
  `20m`) and upgrade. The pod schedules as soon as the request fits.
- Only add nodes if the request is legitimate and the cluster is genuinely
  full, which is not the case for a single oversized request.
