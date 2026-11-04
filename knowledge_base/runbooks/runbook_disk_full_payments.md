---
doc_id: rb_disk_full_payments
doc_type: runbook
service: payments
fault_type: disk_full
severity: sev1
date: 2025-04-14
status: verified
tags: [disk, audit, payment-writes]
correct_actions: [clear_disk_space]
---
# Runbook: Payments storage full
## Symptoms
Disk-used percentage reaches the limit and payment audit or journal writes fail with no-space errors.
## Diagnosis
Locate the full filesystem and classify files before cleanup. Keep charge journals, reconciliation data, and audit records intact.
## Remediation
Use the approved retention policy to remove or archive eligible temporary files, then restore the service's write capacity.
## Verification
Verify audit writes succeed, payment errors settle, and free space remains above the operational reserve.
## Avoid
Do not delete audit records or assume a process restart will reclaim disk space.
