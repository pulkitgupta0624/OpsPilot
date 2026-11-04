---
doc_id: pm_20250330_payments_audit_volume
doc_type: postmortem
service: payments
fault_type: disk_full
severity: sev1
date: 2025-03-30
status: verified
tags: [disk, audit, retention]
---
# Payments audit volume filled before log rotation
## Impact
Payment audit writes failed and new charge attempts returned errors until free space was restored.
## Timeline
01:10 UTC free space fell below reserve; 01:18 no-space errors began; 01:25 eligible archives were moved to approved retention storage.
## Root cause
An audit export retained duplicate compressed files after a change to its rotation naming scheme.
## Contributing factors
Disk alerts fired at 95 percent, leaving little time for the overnight export workload.
## Fix and verification
Archived eligible exports under retention policy, restored disk headroom, and verified new audit writes. Rotation naming was corrected.
## Lessons
Keep audit evidence, but prevent duplicate exports and alert on growth rate as well as capacity.
