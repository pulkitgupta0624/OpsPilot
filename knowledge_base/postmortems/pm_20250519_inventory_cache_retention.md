---
doc_id: pm_20250519_inventory_cache_retention
doc_type: postmortem
service: inventory
fault_type: memory_leak
severity: sev3
date: 2025-05-19
status: verified
tags: [reservation-cache, heap, eviction]
---
# Inventory reservation cache did not evict expired entries
## Impact
Reservation checks became slower after a long-running shift; successful reservations remained available.
## Timeline
06:00 UTC cache size started trending up; 08:20 GC pauses increased; 08:31 inventory was restarted.
## Root cause
An expiry timestamp used local time while the eviction worker compared UTC values, leaving entries resident.
## Contributing factors
Cache age was not included in the service dashboard, and the problem was initially mistaken for a traffic burst.
## Fix and verification
Restarted inventory, normalized timestamps to UTC, and confirmed expired entries disappeared during a soak run.
## Lessons
Track cache entry age and exercise time-zone transitions in expiry tests.
