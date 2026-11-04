---
doc_id: pm_20250819_payments_idle_conn
doc_type: postmortem
service: payments
fault_type: db_pool_exhaustion
severity: sev2
date: 2025-08-19
status: verified
tags: [idle-connections, pool, transaction-cleanup]
---
# Abandoned payment sessions occupied database connections
## Impact
Charge requests experienced acquire timeouts for six minutes; no duplicate settlements were found.
## Timeline
18:10 UTC session occupancy rose; 18:15 timeout errors started; 18:21 stale sessions were closed and pool limits were adjusted.
## Root cause
An exception path skipped transaction cleanup after an authorization provider returned an invalid response.
## Contributing factors
Pool metrics counted busy sessions but did not expose how long each session had been held.
## Fix and verification
Closed stale sessions and added cleanup in a finally block. Fault injection no longer leaves connections occupied.
## Lessons
Measure connection age and make transaction release unconditional on error paths.
