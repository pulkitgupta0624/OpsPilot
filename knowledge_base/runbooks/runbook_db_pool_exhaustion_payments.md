---
doc_id: rb_db_pool_exhaustion_payments
doc_type: runbook
service: payments
fault_type: db_pool_exhaustion
severity: sev2
date: 2025-04-05
status: verified
tags: [database, connection-pool, charge-timeout]
correct_actions: [increase_db_pool]
acceptable_actions: [restart_service]
---
# Runbook: Payments database pool exhaustion
## Symptoms
All payment database connections are busy, acquire timeouts accumulate, and charge latency and errors rise together.
## Diagnosis
Check `db_pool_in_use / db_pool_size`, transaction age, and database connection headroom. Confirm the symptom is not only upstream orders latency.
## Remediation
Increase the payments pool in a small controlled step when the database can accept it. Restarting may release leaked sessions but is a secondary option.
## Verification
Confirm pool wait errors decline, charge requests complete, and database connections remain below the server limit.
## Avoid
Do not retry failed charges without idempotency protection or set the pool above the database connection budget.
