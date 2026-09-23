---
id: err-image-never-pull
failure_class: ErrImageNeverPull
symptoms:
  - "container state.waiting.reason == ErrImageNeverPull"
  - "event message states the image is not present and imagePullPolicy is Never"
  - "pod scheduled onto a node that has never pulled/built the referenced image"
---

## Diagnosis

`ErrImageNeverPull` is distinct from `ImagePullBackOff`: it means the pod's
`imagePullPolicy` is explicitly `Never` (don't attempt a pull at all,
only use an image already present on the node), and the image simply isn't
present on the node the pod landed on. This is common in local dev
clusters (kind/minikube) where images are built/loaded directly onto
specific nodes rather than pushed to a registry. Check:

1. `spec.containers[*].imagePullPolicy` -- confirm it's actually `Never`
   (not the default `IfNotPresent`, which would instead attempt a pull and
   surface as `ImagePullBackOff` if that failed).
2. Which node the pod was scheduled to, and whether the image was
   loaded/built specifically on that node (e.g. via `kind load
   docker-image` or `minikube image load`) rather than cluster-wide.
3. Whether the image tag referenced in the pod spec exactly matches the
   tag that was loaded -- a mismatched tag (e.g. `:latest` vs. a specific
   version) looks identical to "never loaded" from the kubelet's
   perspective.

## Remediation

- Image not loaded on the target node: load it onto that node (or, for
  multi-node kind/minikube clusters, onto every node the pod might be
  scheduled to) before scheduling the pod.
- Tag mismatch: align the loaded image's tag with what the pod spec
  actually references.
- If this recurs across many pods/nodes in a local dev cluster: reconsider
  `imagePullPolicy: Never` in favor of a local registry the cluster's
  nodes can all pull from, so image availability isn't tied to which
  specific node a pod happens to land on.
- This failure class is essentially never seen in a real production
  cluster with a proper registry -- if it shows up outside local dev,
  something is misconfigured about how images reach that cluster.
