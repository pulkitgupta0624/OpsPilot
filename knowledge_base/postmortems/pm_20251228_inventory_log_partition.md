---
doc_id: pm_20251228_inventory_log_partition
doc_type: postmortem
service: inventory
fault_type: disk_full
severity: sev2
date: 2025-12-28
status: verified
tags: [disk, logs, partition]
---
# Inventory log partition filled during a debug rollout
## Impact
Inventory could not persist reservation diagnostics and a portion of stock refreshes were delayed.
## Timeline
22:05 UTC debug logging was enabled; 22:32 the log partition reached capacity; 22:38 logging was reduced and rotated files were archived.
## Root cause
Verbose per-item logs grew much faster than the standard retention estimate.
## Contributing factors
The debug flag had no automatic expiry and log volume was not included in deployment review.
## Fix and verification
Reduced the log level, reclaimed rotated logs under policy, and confirmed reservation writes resumed.
## Lessons
Time-box debug logging and monitor bytes written per service as well as filesystem percentage.
