---
doc_id: pm_20250129_orders_catalog_timeout
doc_type: postmortem
service: orders
fault_type: slow_dependency
severity: sev2
date: 2025-01-29
status: verified
tags: [catalog, timeout, circuit-breaker]
---
# Orders catalog calls stalled during a regional slowdown
## Impact
Order validation p95 exceeded its SLO and the queue grew; completed orders remained consistent.
## Timeline
16:12 UTC catalog latency rose; 16:16 order retries increased; 16:20 the breaker opened and the queue began draining.
## Root cause
The remote catalog region had elevated response time while orders waited synchronously for every lookup.
## Contributing factors
Retries were enabled without sufficient jitter and there was no per-dependency queue limit.
## Fix and verification
Enabled the catalog circuit breaker and bounded retries. Orders latency recovered before the catalog region fully normalized.
## Lessons
Protect the caller from a slow dependency and keep a distinct dependency-health signal.
