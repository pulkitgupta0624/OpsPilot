---
doc_id: pm_20251101_orders_export_spill
doc_type: postmortem
service: orders
fault_type: disk_full
severity: sev2
date: 2025-11-01
status: verified
tags: [disk, export-spill, cleanup]
---
# Orders report export spilled to the root volume
## Impact
Order writes briefly failed after a large report job used the service's remaining disk allocation.
## Timeline
10:00 UTC report began; 10:16 the spill directory expanded; 10:21 the job was stopped and temporary output was cleaned up.
## Root cause
The reporting library selected a default spill path on the same volume as the orders journal.
## Contributing factors
The export did not declare a storage quota or reserve space for transaction writes.
## Fix and verification
Stopped the report, removed its incomplete temporary spill, and moved future exports to a bounded volume. Order persistence recovered.
## Lessons
Reserve disk for durable writes and make every background job declare its scratch location.
