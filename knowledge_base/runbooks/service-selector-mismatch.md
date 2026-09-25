---
id: service-selector-mismatch
failure_class: SelectorMismatch
symptoms:
  - "Service exists and its pods are Running and Ready, but callers get connection refused or no route"
  - "Service Endpoints object is empty (no addresses) although matching pods appear to exist"
  - "callers log 'connection refused' or 'no endpoints available' for a Service name that resolves in DNS"
---

## Diagnosis

SelectorMismatch: the Service's `spec.selector` does not match the labels on
the pods that are supposed to back it, so Kubernetes attaches no pods to it and
its Endpoints stay empty. DNS still resolves the Service name and the pods look
healthy, which is why this is easy to miss: the fault is in the labels, not in
any pod. Confirm in this order:

1. Read the Service's selector (`kubectl get svc <name> -o jsonpath='{.spec.selector}'`).
2. List the Endpoints (`kubectl get endpoints <name>`). An empty `ENDPOINTS`
   column with Ready pods around confirms it.
3. Compare the selector to the real pod labels (`kubectl get pods --show-labels`).
   Look for a renamed key or value, a typo (`app: catlog`), or a label that
   was changed on the Deployment's pod template but not on the Service.
4. Rule out readiness: pods that are Running but not Ready are also absent from
   Endpoints. If the pods are Ready and the selector matches nothing, it is a
   selector mismatch; if the selector matches but pods are NotReady, it is a
   probe failure instead.

## Remediation

- Make the two agree. Fix whichever side is wrong: usually correct the Service
  selector to the pod template's labels, or restore the label on the pod
  template. Prefer changing the Service, because changing pod-template labels
  forces a rollout.
- Fix it in the source manifest or chart, not by editing the live object, so
  the next deploy does not reintroduce it.
- Note that a Deployment's own `spec.selector` is immutable; do not try to
  patch it to match a Service.
- After the fix, `kubectl get endpoints <name>` should list the pod IPs and
  callers recover without restarting.
