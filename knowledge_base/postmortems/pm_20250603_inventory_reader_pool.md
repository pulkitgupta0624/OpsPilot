---
doc_id: pm_20250603_inventory_reader_pool
doc_type: postmortem
service: inventory
fault_type: db_pool_exhaustion
severity: sev3
date: 2025-06-03
status: verified
tags: [reader-pool, reservations, database]
---
# Inventory reservation readers exhausted a small connection pool
## Impact
Stock checks queued and order placement saw a short increase in reservation timeouts.
## Timeline
07:45 UTC a scheduled catalogue refresh overlapped order traffic; 07:51 readers saturated; 08:02 pool capacity was raised.
## Root cause
The read pool was sized for the previous refresh cadence and could not absorb both refresh and reservation queries.
## Contributing factors
The refresh job had no concurrency cap and the service SLO dashboard emphasized write traffic.
## Fix and verification
Increased reader capacity after checking database headroom and capped refresh concurrency. Reservation latency returned to target.
## Lessons
Load-test background jobs alongside interactive requests when sizing a shared pool.
