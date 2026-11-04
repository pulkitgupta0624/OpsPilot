---
doc_id: pm_20251114_inventory_gc_pressure
doc_type: postmortem
service: inventory
fault_type: memory_leak
severity: sev3
date: 2025-11-14
status: verified
tags: [session-object, garbage-collection, reservations]
---
# Inventory workers accumulated reservation session objects
## Impact
Reservation p95 latency exceeded its target for twelve minutes, without evidence of lost stock updates.
## Timeline
14:01 UTC session count rose; 14:22 GC duration increased; 14:29 workers were restarted after draining.
## Root cause
A completed reservation session remained reachable from a metrics callback closure.
## Contributing factors
Heap snapshots were not part of the routine response checklist, so diagnosis began with database checks.
## Fix and verification
Restarted workers and detached the callback after completion. A two-hour soak showed stable session counts.
## Lessons
Include object-retention evidence and callback lifecycle ownership in memory investigations.
