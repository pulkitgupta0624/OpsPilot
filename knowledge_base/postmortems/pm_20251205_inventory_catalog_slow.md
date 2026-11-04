---
doc_id: pm_20251205_inventory_catalog_slow
doc_type: postmortem
service: inventory
fault_type: slow_dependency
severity: sev3
date: 2025-12-05
status: verified
tags: [catalog, circuit-breaker, worker-pool]
---
# Inventory catalog enrichment delayed reservation responses
## Impact
Reservation latency increased during a catalogue refresh, but stock writes were not lost.
## Timeline
21:02 UTC enrichment requests slowed; 21:07 worker queue grew; 21:15 the dependency breaker opened.
## Root cause
An optional catalog enrichment call was awaited before returning a reservation response.
## Contributing factors
The enrichment path shared workers with required stock checks and had no fallback cache.
## Fix and verification
Enabled the breaker and returned a clearly marked stale catalog value for the bounded fallback window. Reservation p95 recovered.
## Lessons
Keep optional enrichment outside the critical reservation path and label fallback data freshness.
