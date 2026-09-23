---
id: image-pull-backoff
failure_class: ImagePullBackOff
symptoms:
  - "container state.waiting.reason == ImagePullBackOff (or ErrImagePull first)"
  - "event reason Failed or ErrImagePull, message mentions the image reference"
  - "pod never leaves Pending/ContainerCreating"
---

## Diagnosis

`ImagePullBackOff` means the kubelet could not pull the container image and
is now backing off retries. `ErrImagePull` is the immediate first-attempt
version of the same problem; `ImagePullBackOff` is what it becomes after
repeated failures. Check:

1. The exact image reference in `spec.containers[*].image` -- typos in the
   repository, name, or tag are the single most common cause.
2. The event message (reason `Failed`/`ErrImagePull`) for the underlying
   error: "manifest unknown" (tag/image doesn't exist), "not found"
   (repository doesn't exist or is private), "unauthorized"/"denied"
   (missing or wrong pull credentials), or a DNS/network error reaching the
   registry.
3. Whether the image is in a private registry and, if so, whether the pod's
   `imagePullSecrets` are configured and reference a valid, non-expired
   credential.
4. Whether the registry is reachable at all from the cluster's nodes (a
   network policy or egress restriction can produce the same symptom as a
   bad credential).

## Remediation

- Typo'd image/tag: fix the reference and redeploy.
- Private registry, missing/invalid credentials: create or fix the
  `imagePullSecrets` referenced by the pod's ServiceAccount or spec.
- Image genuinely doesn't exist at that tag: rebuild/push it, or point the
  deployment at a tag that does exist.
- Registry unreachable: this is a network/infra issue, not something to
  patch at the deployment level -- escalate to whoever owns cluster egress
  or the registry itself.
