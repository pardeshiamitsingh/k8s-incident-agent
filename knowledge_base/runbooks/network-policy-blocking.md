---
id: network-policy-blocking
failure_class: NetworkPolicyBlocking
symptoms:
  - "connection timed out (not refused) between two services that are both Running and Ready"
  - "a NetworkPolicy selects the destination pod and does not allow the caller"
  - "traffic worked before a NetworkPolicy was applied or a pod label changed"
---

## Diagnosis

NetworkPolicyBlocking: a NetworkPolicy selects the destination pod (or the
caller, for egress) and its rules admit no path for this traffic, so packets
are silently dropped. The signature is a timeout, not a refusal: `connection
refused` means something answered and rejected; `timed out` or `i/o timeout`
means nothing came back. Both pods are healthy and the Service has
Endpoints, so pod status and events show nothing wrong. Confirm:

1. List policies in the destination namespace (`kubectl get networkpolicy`) and
   read each `podSelector`. An empty `podSelector: {}` selects every pod.
2. A policy with `policyTypes: [Ingress]` and no `ingress` rules is deny-all
   for the selected pods.
3. Check the `from` peers of each ingress rule: do they match the caller's
   namespace labels and pod labels? A common cause is a `podSelector` peer that
   omits the `namespaceSelector` (same-namespace only), or a caller whose labels
   changed.
4. For egress-restricting policies on the caller, check DNS egress (UDP/TCP 53)
   is allowed, or the symptom becomes name resolution failure.
5. Confirm the CNI enforces NetworkPolicy at all; on a cluster whose CNI does
   not, policies have no effect and a timeout has another cause.

## Remediation

- Add or correct an allow rule so the intended caller can reach the
  destination on the required port, keeping the policy as narrow as possible.
- Do not delete the policy to make the symptom go away; it may be a deliberate
  isolation control. Confirm with its owner first.
- Verify with a test request from the caller pod after the change, and keep
  the policy in the source manifest or chart rather than editing it live.
