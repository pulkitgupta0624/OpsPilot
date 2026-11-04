---
doc_id: rb_disk_full_orders
doc_type: runbook
service: orders
fault_type: disk_full
severity: sev2
date: 2025-04-13
status: verified
tags: [disk, storage, write-failure]
correct_actions: [clear_disk_space]
---
# Runbook: Orders disk capacity exhausted
## Symptoms
Disk usage approaches 100 percent and write paths fail with no-space errors; request errors may rise after capacity is exhausted.
## Diagnosis
Identify the growing directory and distinguish logs, temporary exports, and durable order data. Confirm the volume before cleanup.
## Remediation
Remove or rotate only approved temporary files and old logs; preserve durable order records and audit evidence.
## Verification
Confirm free space is restored, write errors stop, and normal order persistence succeeds.
## Avoid
Do not restart as the only action; a restart does not free a full volume.
