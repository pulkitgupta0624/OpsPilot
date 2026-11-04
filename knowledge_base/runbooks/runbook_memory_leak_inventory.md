---
doc_id: rb_memory_leak_inventory
doc_type: runbook
service: inventory
fault_type: memory_leak
severity: sev3
date: 2025-04-03
status: verified
tags: [memory, heap, reservation-cache]
correct_actions: [restart_service]
---
# Runbook: Inventory reservation memory growth
## Symptoms
Inventory memory climbs during steady reservation traffic, followed by slower garbage collection and rising p95 latency.
## Diagnosis
Check reservation-cache eviction, open request contexts, and memory trend by worker. A single high sample is not enough to call a leak.
## Remediation
Drain reservation requests and restart the affected inventory instance. Temporarily scale out only if queue depth threatens the checkout SLO.
## Verification
Verify the heap returns to normal, reservation errors stop rising, and queue depth drains.
## Avoid
Do not clear active reservations to free memory; reconcile their owners first.
