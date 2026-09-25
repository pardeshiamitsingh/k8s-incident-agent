# Spec: Dependency-failure diagnosis

**Status:** draft
**Constitution version this spec complies with:** 1.7.0

## Problem

Today the agent diagnoses what is wrong *inside* a pod: its container state
and its events. Many real incidents are not visible there. A service can be
healthy while unreachable because its Service selector matches no pods, a
NetworkPolicy drops its traffic, or the thing it depends on is down. The
symptom appears in the caller's logs as "connection refused" or a timeout,
and the classifier returns `Unknown`. Spec 003 named this gap ("extending the
collector's model... is future work"). This spec closes it for three failure
classes, using the ecommerce demo (spec 011) as the test bed.

## Scope

**In:**
- New read-only collectors for `Service`, `Endpoints` and `NetworkPolicy` in
  the target namespace.
- New evidence fields on `IncidentEvidence` for them.
- New deterministic (LLM-free) classifier rules producing:
  - `SelectorMismatch`: a Service has zero ready endpoints while pods exist
    whose labels do not satisfy its selector.
  - `NetworkPolicyBlocking`: a NetworkPolicy selects the pod and its ingress
    or egress rules admit no path to the traffic the logs show failing.
  - `DependencyFailure`: the object's logs show connection failures to a
    host that resolves to a Service in the namespace, and that Service has no
    ready endpoints because its backing workload is unhealthy.
- Three runbooks (one per class) and the failure scenarios in the ecommerce
  chart (`selector-mismatch-catalog`, `netpol-block-orders`,
  `cascade-postgres`).
- Widened read-only RBAC: `get`/`list`/`watch` on `services`, `endpoints`
  (core) and `networkpolicies` (`networking.k8s.io`).

**Out:**
- Any write access, and any change to `ObjectRef` kinds (still Pod and
  Deployment; the new evidence hangs off the object being diagnosed).
- Ingress, Gateway, service mesh and DNS-level diagnosis.
- Automatically walking a multi-hop dependency graph beyond one hop.
- LLM-based classification (kept deterministic, as in Phase 3).

## Constitution check

- Propose-only by default: complies. Collectors only read; the plan is still a
  proposal.
- Read-only RBAC: complies, with a real widening recorded in amendment 1.7.0:
  three more resource kinds, verbs still only `get`/`list`/`watch`.
- Local-first, no external LLM calls: complies. No new LLM calls; classifier
  rules are deterministic.
- Every diagnosis is explainable: strengthened. Each new class cites the
  specific Service selector, endpoint counts, policy name or log line that
  triggered it.
- Full audit trail: unchanged.

## Design

**Collectors** (`collectors/`): `get_services(namespace)`,
`get_endpoints(namespace)`, `get_network_policies(namespace)` return Pydantic
snapshots (Service: selector, ports; Endpoints: ready/not-ready address
counts; NetworkPolicy: pod selector, policy types, ingress/egress rule
summaries). `collect_evidence` attaches them to `IncidentEvidence` as
`services`, `endpoints`, `network_policies`, defaulting to empty lists so
existing evidence, fixtures and tests are unaffected.

**Classifier** (`agent/classification.py`): add rule functions alongside the
reason table, each returning evidence strings so the diagnosis can cite them.
Rules run after the existing reason matching and only add classes; existing
classes are never removed. `Unknown` is returned only if nothing at all
matched, as today.
- `SelectorMismatch`: for each Service with selector S and zero ready
  endpoints, if the namespace has pods and none carries labels satisfying S
  while some carry labels differing from S by a key or value.
- `NetworkPolicyBlocking`: a policy's `podSelector` matches the object's
  pods and its rules for the relevant direction are empty (deny-all) or list
  no peer matching the failing caller, and the logs contain a timeout
  signature (`timed out`, `i/o timeout`) rather than `refused`.
- `DependencyFailure`: log lines matching connection-failure signatures
  (`connection refused`, `could not translate host name`, `no route`) that
  name a host equal to a Service in the namespace whose endpoints are empty.
  Timeouts point to `NetworkPolicyBlocking`; refusals with empty endpoints
  point to `DependencyFailure` or `SelectorMismatch`, and precedence is
  `SelectorMismatch` > `DependencyFailure` when the dependency's own pods are
  healthy but unselected.

**Retrieval and prompts:** unchanged. New classes flow through
`REASON`-independent retrieval by class name; the diagnose prompt already
receives all evidence and gains the new fields.

**RBAC:** the required rules are documented in the demo README and in the
constitution amendment. This repo has no agent RBAC manifest today, since the
agent runs on the operator's kubeconfig; adding one is an open question.

## Acceptance criteria

- Collectors and rules are unit-tested with fabricated snapshots, including
  negative cases (healthy Service, matching selector, allow-all policy) that
  must not fire.
- Existing classifier and evidence tests pass unchanged.
- Against the ecommerce demo on kind, each of the three scenarios classifies
  as its intended class and the diagnosis cites the triggering selector,
  policy or log line.
- The three runbooks are retrieved when their class is queried.
- A `/diagnose/query` for the symptom service (for example "cart can't reach
  redis") resolves and completes with the right root cause.
- No `create`/`update`/`patch`/`delete` call exists in any new collector
  (grep-based test).

## Open questions

- **NetworkPolicy enforcement on kind:** the default CNI may not enforce
  NetworkPolicy. If the cluster does not, `netpol-block-orders` cannot be
  demonstrated without installing a policy-capable CNI (for example Calico),
  which is new cluster tooling to decide on before implementing that scenario.
- **Heuristic precision:** the log-signature rules are deliberately narrow;
  expect false negatives on unusual client error strings.
- **Cascade depth:** one hop only; deeper chains are left to the LLM reading
  the raw evidence.
- **RBAC manifest:** whether to add a checked-in ServiceAccount/ClusterRole for
  running the agent in-cluster, given none exists today.
