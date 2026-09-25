---
id: ecommerce-catalog-image-pull
failure_class: ImagePullBackOff
symptoms:
  - "ecommerce catalog pod in ImagePullBackOff or ErrImagePull, event Failed to pull image"
  - "catalog image tag hashicorp/http-echo:1.0-does-not-exist not found"
---

## Diagnosis

The `catalog` Deployment in namespace `ecommerce` uses
`hashicorp/http-echo`. If its pod is in `ImagePullBackOff` and the events show
`manifest unknown` or `not found`, the image tag does not exist in the
registry. Read the exact image reference from the Deployment (or the pod's
container status) and compare the tag to the published tags. A tag such as
`1.0-does-not-exist` is a typo or a tag that was never pushed. A registry
auth or network error message would point elsewhere.

## Remediation

- Set the catalog image back to a valid tag (the chart default is
  `hashicorp/http-echo:1.0`) and upgrade, or roll back the release:
  `helm rollback ecommerce <revision> -n ecommerce`.
- The old ReplicaSet keeps serving during a failed rollout, so no traffic is
  lost, but the new version is not running until the tag is fixed.
