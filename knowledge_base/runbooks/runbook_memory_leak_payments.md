---
doc_id: rb_memory_leak_payments
doc_type: runbook
service: payments
fault_type: memory_leak
severity: sev2
date: 2025-04-02
status: verified
tags: [memory, heap, payment-workers]
correct_actions: [restart_service]
---
# Runbook: Payments worker memory leak
## Symptoms
Payments heap usage grows steadily while completed charge volume stays level; GC pauses and occasional worker restarts follow.
## Diagnosis
Inspect worker retention and recent queue consumers. Separate a gradual leak from a legitimate batch that has not completed.
## Remediation
Drain in-flight charges, restart the affected payments process, and keep retry handling idempotent. Scale out only as short-lived capacity relief.
## Verification
Memory should fall after restart, charge retries should settle, and the restart counter should remain flat.
## Avoid
Do not replay an entire charge batch without checking idempotency keys.
