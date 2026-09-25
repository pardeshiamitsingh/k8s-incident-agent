---
id: ecommerce-cart-missing-secret
failure_class: CreateContainerConfigError
symptoms:
  - "ecommerce cart pod stuck in CreateContainerConfigError, secret not found"
  - "cart references Secret cart-redis-auth-v2 which does not exist"
---

## Diagnosis

The `cart` Deployment in namespace `ecommerce` reads its environment from a
Secret via `envFrom`. `CreateContainerConfigError` with a message like
`secret "cart-redis-auth-v2" not found` means the pod spec names a Secret that
does not exist in the namespace, so the container is never created and there
are no logs. Compare the Secret name in the Deployment with
`kubectl get secrets -n ecommerce`: the healthy chart uses `cart-redis-auth`.

## Remediation

- Point the Deployment back at the existing Secret (`cart-redis-auth`), or
  create the missing Secret with the expected keys.
- Fix it in the chart rather than by editing the live object, so the next
  upgrade does not reintroduce the bad reference.
