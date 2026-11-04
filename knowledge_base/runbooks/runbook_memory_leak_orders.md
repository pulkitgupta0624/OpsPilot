---
doc_id: rb_memory_leak_orders
doc_type: runbook
service: orders
fault_type: memory_leak
severity: sev2
date: 2025-04-01
status: verified
tags: [memory, heap, garbage-collection]
correct_actions: [restart_service]
---
# Runbook: Orders memory growth
## Symptoms
Memory rises across several windows, garbage collection pauses become longer, and request latency may climb before restarts.
## Diagnosis
Compare the memory slope with request volume and deployment history. Check retained order objects and cache eviction counts; a short traffic burst alone should decay.
## Remediation
Drain orders traffic and restart the service to release the leaked heap. Scaling out is temporary containment, not a correction.
## Verification
Confirm memory returns near its baseline, restart count stops increasing, and p95 latency remains stable for five minutes.
## Avoid
Do not raise the memory limit as the only fix; it delays the next out-of-memory restart.
