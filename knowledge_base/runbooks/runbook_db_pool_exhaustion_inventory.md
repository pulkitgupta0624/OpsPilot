---
doc_id: rb_db_pool_exhaustion_inventory
doc_type: runbook
service: inventory
fault_type: db_pool_exhaustion
severity: sev3
date: 2025-04-06
status: verified
tags: [database, connection-pool, reservations]
correct_actions: [increase_db_pool]
---
# Runbook: Inventory reservation pool saturation
## Symptoms
Reservation transactions wait for a database connection; in-use count reaches pool size while reservation latency increases.
## Diagnosis
Inspect open reservation transactions and database-wide connection headroom. Check whether one worker is holding a session after request completion.
## Remediation
Raise the inventory pool modestly only after verifying shared database capacity, then shorten or close stale transactions.
## Verification
Pool utilization should leave the ceiling, reservation timeouts should decline, and queue depth should recover.
## Avoid
Do not scale inventory instances without calculating the combined connection demand.
