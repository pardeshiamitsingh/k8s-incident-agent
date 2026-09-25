---
id: ecommerce-orders-db-auth
failure_class: CrashLoopBackOff
symptoms:
  - "ecommerce orders pod in CrashLoopBackOff, logs: password authentication failed for user shop"
  - "orders cannot authenticate to postgres, exits with FATAL"
---

## Diagnosis

CrashLoopBackOff on the ecommerce `orders` service: it checks its Postgres
login at startup and exits non-zero if that fails, so the pod restarts in a
loop. Read the logs: `FATAL:
password authentication failed for user "shop"` followed by `orders cannot
authenticate to postgres` means the password in the `orders-db` Secret
(`DB_PASSWORD`) does not match the password Postgres was initialised with
(`POSTGRES_PASSWORD` in `postgres-credentials`). Postgres itself is healthy,
so this is a credentials mismatch, not a database outage: check that
`postgres` pods are Ready before blaming the database.

## Remediation

- Make the two Secrets agree: set `orders-db` `DB_PASSWORD` to the password in
  `postgres-credentials`, via the chart value `ordersDbPassword`, and upgrade.
  The orders pod template carries a checksum of the credential, so it restarts.
- If the password was intentionally rotated, rotate it in Postgres
  (`ALTER USER shop PASSWORD ...`) and in both Secrets together.
