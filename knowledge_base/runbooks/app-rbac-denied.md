---
id: app-rbac-denied
failure_class: AppRBACDenied
symptoms:
  - "application logs show 'forbidden' / 'Unauthorized' / 403 from the K8s API"
  - "error message names a verb+resource, e.g. 'cannot list resource \"pods\" in API group ...'"
  - "failure appears only when the app itself tries to call the K8s API (client-go, kubectl inside the pod, an operator/controller)"
---

## Diagnosis

This is about the *workload's own* ServiceAccount lacking permission to
call the Kubernetes API -- distinct from the incident agent's own RBAC
(which is fixed, read-only, and unrelated to this). It only applies to
applications that themselves talk to the K8s API (operators, controllers,
apps doing self-discovery, CI jobs using `kubectl`, etc.). Check:

1. The exact error message -- it names the verb (`get`/`list`/`watch`/
   `create`/...), the resource, and often the API group and namespace
   scope that was denied.
2. Which ServiceAccount the pod is actually running as
   (`spec.serviceAccountName`, defaulting to `default` if unset) --
   confirm this matches what you expect the app to be using.
3. The `Role`/`ClusterRole` and `RoleBinding`/`ClusterRoleBinding` that
   are supposed to grant that ServiceAccount the needed permission --
   verify the binding actually references the right ServiceAccount
   (namespace + name), and the Role actually lists the verb/resource/API
   group the app needs.
4. Whether the permission is namespaced correctly -- a `Role`+`RoleBinding`
   only grants access within that one namespace; an app that needs
   cluster-wide access (e.g. watching pods across all namespaces) needs a
   `ClusterRole`+`ClusterRoleBinding` instead.

## Remediation

- Missing/incomplete `Role`: add the specific verb+resource(+API group)
  the app's error names -- avoid reflexively granting broad wildcard
  permissions (`*`/`*`) just to make the error go away.
- Wrong/missing `RoleBinding`: fix it to reference the ServiceAccount the
  pod actually runs as, in the correct namespace.
- App needs cluster scope but only has a namespaced Role: switch to a
  `ClusterRole`+`ClusterRoleBinding`, deliberately, rather than granting
  namespaced access in every namespace as a workaround.
- Always grant the minimum verbs/resources the app's own error messages
  actually name -- this mirrors why the incident agent itself is
  read-only-only (constitution principle 2); the same minimal-privilege
  reasoning applies to every workload's ServiceAccount, not just the
  agent's own.
