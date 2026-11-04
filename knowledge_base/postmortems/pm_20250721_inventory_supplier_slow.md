---
doc_id: pm_20250721_inventory_supplier_slow
doc_type: postmortem
service: inventory
fault_type: slow_dependency
severity: sev3
date: 2025-07-21
status: verified
tags: [supplier, reservation, timeout]
---
# Inventory supplier availability calls exceeded their deadline
## Impact
Some new reservations waited longer than target; existing inventory reads continued to work.
## Timeline
09:00 UTC supplier p95 increased; 09:06 inventory queue grew; 09:12 the supplier breaker opened.
## Root cause
Supplier availability calls shared a worker pool with fast local reservation reads and had no isolation boundary.
## Contributing factors
Timeouts were retried twice even when the supplier was already returning late responses.
## Fix and verification
Enabled the circuit breaker and isolated supplier work. Local reads remained responsive during a repeat drill.
## Lessons
Separate slow external work from latency-sensitive local request capacity.
