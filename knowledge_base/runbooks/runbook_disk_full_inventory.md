---
doc_id: rb_disk_full_inventory
doc_type: runbook
service: inventory
fault_type: disk_full
severity: sev2
date: 2025-04-15
status: verified
tags: [disk, snapshots, reservation-data]
correct_actions: [clear_disk_space]
---
# Runbook: Inventory volume at capacity
## Symptoms
Inventory disk use rises to the capacity ceiling and snapshot or reservation writes return no-space errors.
## Diagnosis
Check snapshot retention and temporary import files. Identify the exact volume and confirm backups exist before cleanup.
## Remediation
Remove expired snapshots or temporary data under the retention policy; preserve the current stock ledger and reservation journal.
## Verification
Confirm snapshot and reservation writes succeed and disk usage stays below the warning threshold.
## Avoid
Do not delete the latest recoverable snapshot or clear active reservation state.
