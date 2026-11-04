---
doc_id: pm_20250904_orders_retry_storm
doc_type: postmortem
service: orders
fault_type: slow_dependency
severity: sev1
date: 2025-09-04
status: verified
tags: [retry-storm, queue, dependency]
---
# Orders retry storm prolonged an inventory dependency incident
## Impact
Queue depth and p95 latency rose across orders while inventory CPU stayed normal and its remote lookup was slow.
## Timeline
19:40 UTC lookup latency rose; 19:44 synchronized retries began; 19:49 the breaker opened and queue pressure eased.
## Root cause
A fixed retry schedule caused many orders workers to retry the same slow inventory call at once.
## Contributing factors
The alert named orders first and did not initially include dependency spans or retry rate.
## Fix and verification
Enabled the inventory breaker, added jitter and capped retries. The queue drained without scaling the healthy inventory process.
## Lessons
Correlate callers and dependencies before treating a queue spike as local saturation.
