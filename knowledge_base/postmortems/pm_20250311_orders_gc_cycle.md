---
doc_id: pm_20250311_orders_gc_cycle
doc_type: postmortem
service: orders
fault_type: memory_leak
severity: sev2
date: 2025-03-11
status: verified
tags: [heap, garbage-collection, cache]
---
# Orders garbage-collection cycle caused by retained responses
## Impact
Checkout p95 latency doubled during a weekday peak; a small number of requests retried, with no lost orders.
## Timeline
09:10 UTC memory began rising; 09:32 GC pauses crossed the warning threshold; 09:41 the service was drained and restarted.
## Root cause
A response cache retained serialized order summaries after their TTL because eviction ran only on cache writes.
## Contributing factors
The alert tracked memory level but did not show the slope or cache eviction count.
## Fix and verification
Restarted orders for recovery, then repaired TTL eviction. Heap growth stopped under replay traffic and p95 returned to baseline.
## Lessons
Measure retained-object growth and test idle-time eviction, not only high-volume writes.
