---
doc_id: rb_slow_dependency_inventory
doc_type: runbook
service: inventory
fault_type: slow_dependency
severity: sev3
date: 2025-04-09
status: verified
tags: [dependency, reservation, timeout]
correct_actions: [enable_circuit_breaker]
---
# Runbook: Inventory dependency slowdown
## Symptoms
Reservation calls slow down with upstream timeout messages while inventory CPU remains ordinary and its request queue grows.
## Diagnosis
Trace the slow call to the supplier or stock dependency. Check dependency latency and retries before changing local worker counts.
## Remediation
Enable the circuit breaker for the specific dependency and let callers use the documented temporary-unavailable path.
## Verification
Confirm inventory queue depth and orders latency improve, then verify the dependency is healthy before reopening traffic.
## Avoid
Do not disable the breaker while timeout rates are still elevated.
