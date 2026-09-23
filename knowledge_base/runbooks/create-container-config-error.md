---
id: create-container-config-error
failure_class: CreateContainerConfigError
symptoms:
  - "container state.waiting.reason == CreateContainerConfigError"
  - "event message references a missing ConfigMap or Secret by name"
  - "container never reaches Running, pod stuck ContainerCreating/Pending"
---

## Diagnosis

`CreateContainerConfigError` means the kubelet cannot even start the
container because a config dependency it needs is missing -- most
commonly a `ConfigMap` or `Secret` referenced via `envFrom`, `env[].valueFrom`,
or a mounted volume that doesn't exist (or is missing a specific key).
Check:

1. The event message directly -- it names the missing `ConfigMap`/`Secret`
   (and sometimes the specific key) that couldn't be resolved.
2. The pod spec's `envFrom`, `env[].valueFrom.configMapKeyRef` /
   `secretKeyRef`, and any `configMap`/`secret` volumes, cross-referenced
   against what actually exists in the namespace (`kubectl get configmap`,
   `kubectl get secret`).
3. Whether the resource exists but in the wrong namespace -- a ConfigMap
   in the wrong namespace looks identical to "doesn't exist" from the
   pod's perspective.
4. Whether the resource exists but is missing the specific key the pod
   references (the resource itself is present, but one key inside it
   isn't).

## Remediation

- Missing resource entirely: create the `ConfigMap`/`Secret` with the
  expected name in the correct namespace.
- Resource exists, missing key: add the missing key to the
  `ConfigMap`/`Secret`, or fix the pod spec's key reference if it's simply
  wrong.
- If the reference is optional in intent (the app can run without it):
  mark it `optional: true` in the pod spec so a missing resource doesn't
  block startup -- but only do this if the application genuinely handles
  the absence gracefully.
- This is always a configuration/deployment ordering issue -- never an
  application code bug by itself.
