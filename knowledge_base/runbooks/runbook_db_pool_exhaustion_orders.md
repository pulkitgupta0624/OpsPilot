---
doc_id: rb_db_pool_exhaustion_orders
doc_type: runbook
service: orders
fault_type: db_pool_exhaustion
severity: sev2
date: 2025-04-04
status: verified
tags: [database, connection-pool, checkout]
correct_actions: [increase_db_pool]
---
# Runbook: Orders database pool saturation
## Symptoms
Pool utilization stays near its configured maximum, checkout latency rises, and connection-acquire timeouts appear.
## Diagnosis
Compare in-use connections with pool size and inspect checkout transaction duration. Verify the database has headroom before changing the limit.
## Remediation
Increase the orders pool by a bounded increment after confirming database capacity; review long transactions and release connections promptly.
## Verification
Pool wait time and checkout errors should fall while database CPU and connection limits remain safe.
## Avoid
Do not increase every service pool at once; that can overload the shared database.
