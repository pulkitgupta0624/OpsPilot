---
doc_id: pm_20250217_payments_pool_wait
doc_type: postmortem
service: payments
fault_type: db_pool_exhaustion
severity: sev2
date: 2025-02-17
status: verified
tags: [connection-pool, authorization, transaction]
---
# Payment authorization transactions exhausted the pool
## Impact
Payment p95 latency increased and some authorizations timed out; idempotency keys prevented duplicate charges.
## Timeline
10:02 UTC pool use reached its limit; 10:08 acquire timeouts began; 10:14 the pool was raised after database capacity review.
## Root cause
Authorization transactions held a connection while waiting on a remote risk response.
## Contributing factors
The pool alert lacked transaction-age context and the timeout retry policy added short bursts of demand.
## Fix and verification
Increased pool size within the database connection budget, then moved the remote call outside the transaction. Wait time normalized.
## Lessons
A larger pool can restore service, but shorten connection hold time to prevent recurrence.
