---
doc_id: pm_20250426_orders_checkout_pool
doc_type: postmortem
service: orders
fault_type: db_pool_exhaustion
severity: sev2
date: 2025-04-26
status: verified
tags: [checkout, pool-wait, database]
---
# Orders checkout connections remained busy during a query change
## Impact
Checkout responses slowed for nine minutes while order creation stayed available at reduced throughput.
## Timeline
15:20 UTC a query rollout began; 15:27 pool saturation appeared; 15:34 the pool was adjusted and the query reverted.
## Root cause
The new checkout query scanned an unindexed status column and held connections longer than expected.
## Contributing factors
Pool saturation was initially treated as a connection leak rather than correlated with query duration and release version.
## Fix and verification
Raised the pool by a bounded amount, reverted the query, then confirmed wait time and database CPU fell.
## Lessons
Inspect query duration and deployment history before changing pool limits.
