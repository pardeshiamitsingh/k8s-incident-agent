---
id: dns-resolution-failure
failure_class: DNSResolutionFailure
symptoms:
  - "application logs show 'name resolution failed' / 'no such host' / getaddrinfo errors"
  - "in-cluster Service names or external hostnames fail to resolve from inside the pod"
  - "CoreDNS pods unhealthy or CoreDNS-related events in kube-system"
---

## Diagnosis

DNS resolution failures inside a pod are almost always one of a small set
of causes -- narrow down before assuming it's CoreDNS itself:

1. Confirm the failure is actually DNS and not connectivity: exec into the
   pod (or a debug pod in the same namespace) and try resolving the exact
   hostname the app failed on, e.g. `nslookup <service>.<namespace>.svc`.
2. If in-cluster Service names fail but external names resolve (or vice
   versa): check the pod's `dnsPolicy` and `dnsConfig` -- a custom
   `dnsConfig` or `dnsPolicy: None` can break cluster-internal resolution
   while leaving external DNS working, or the reverse.
3. If *all* DNS fails cluster-wide (not just this pod): check CoreDNS pod
   health in `kube-system` directly -- CrashLoopBackOff or resource
   pressure on CoreDNS itself will manifest as DNS failures everywhere,
   not just in one workload.
4. If only *this* pod/namespace is affected: check for a `NetworkPolicy`
   blocking egress to the CoreDNS Service/port (UDP/TCP 53), which
   produces DNS-specific failures while other traffic may still work.
5. Intermittent (not constant) failures often point at CoreDNS being
   under-provisioned for the cluster's query volume rather than a
   config error.

## Remediation

- Pod-level `dnsPolicy`/`dnsConfig` misconfiguration: fix it to
  `ClusterFirst` (the default) unless there's a specific, understood
  reason to override it.
- CoreDNS itself unhealthy: treat as a cluster-infra incident, not a
  per-workload fix -- restart/scale CoreDNS, investigate its own
  logs/events.
- NetworkPolicy blocking DNS egress: add an explicit allow rule for
  UDP/TCP port 53 to the CoreDNS Service, since DNS is easy to
  accidentally block when writing restrictive egress policies.
- CoreDNS under-provisioned for query volume: scale CoreDNS replicas or
  add caching, rather than working around it per-application.
