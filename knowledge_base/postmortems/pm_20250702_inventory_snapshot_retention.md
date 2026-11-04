---
doc_id: pm_20250702_inventory_snapshot_retention
doc_type: postmortem
service: inventory
fault_type: disk_full
severity: sev2
date: 2025-07-02
status: verified
tags: [disk, snapshots, retention]
---
# Inventory snapshots exceeded the retention budget
## Impact
Snapshot writes stopped and inventory refreshes became stale; live reservation reads continued from the last good snapshot.
## Timeline
03:00 UTC snapshot volume accelerated; 03:28 disk reached its warning limit; 03:36 expired snapshots were pruned after backup verification.
## Root cause
Retention was configured by count, but snapshot size had grown as catalogue history expanded.
## Contributing factors
Capacity alerts showed the percentage used but not the projected time to full.
## Fix and verification
Pruned only snapshots older than the recovery window and verified a new snapshot completed successfully.
## Lessons
Enforce retention by bytes and age, and keep one known-good recovery point.
