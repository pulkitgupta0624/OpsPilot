---
doc_id: pm_20251212_payments_leaked_sessions
doc_type: postmortem
service: payments
fault_type: db_pool_exhaustion
severity: sev1
date: 2025-12-12
status: verified
tags: [leaked-sessions, idempotency, database]
---
# Payment reconciliation leaked idle sessions
## Impact
Reconciliation and online charges competed for connections; a limited number of charges timed out and were safely retried.
## Timeline
02:00 UTC reconciliation started; 02:18 pool use reached its ceiling; 02:27 the job was paused and stale sessions released.
## Root cause
The reconciliation cursor opened a transaction per account but closed it only after the whole run.
## Contributing factors
Batch duration and online connection demand were not included in capacity planning.
## Fix and verification
Released each cursor after its account batch, then increased the pool within the server limit. Both workloads completed without waits.
## Lessons
Keep transactions short and reserve connection capacity for interactive payment traffic.
