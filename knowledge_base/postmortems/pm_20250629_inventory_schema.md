---
doc_id: pm_20250629_inventory_schema
doc_type: postmortem
service: inventory
fault_type: bad_deployment
severity: sev2
date: 2025-06-29
status: verified
tags: [deployment, schema, reservation]
---
# Inventory deploy expected a field absent from older stock rows
## Impact
Reservation reads returned errors for older items after a code deployment; recent stock records were unaffected.
## Timeline
14:00 UTC release began; 14:05 schema exceptions appeared; 14:11 rollback completed.
## Root cause
The new application version assumed a backfilled warehouse-zone field before the data migration had finished.
## Contributing factors
The rollout did not gate on migration completion and canary records were all recently created.
## Fix and verification
Rolled back, completed the additive migration, then deployed with a compatibility check. Older records loaded correctly.
## Lessons
Use expand-and-contract migrations and test reads against old as well as new records.
