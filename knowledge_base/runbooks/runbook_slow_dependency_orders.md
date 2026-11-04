---
doc_id: rb_slow_dependency_orders
doc_type: runbook
service: orders
fault_type: slow_dependency
severity: sev2
date: 2025-04-07
status: verified
tags: [dependency, timeout, circuit-breaker]
correct_actions: [enable_circuit_breaker]
acceptable_actions: [scale_out]
---
# Runbook: Orders blocked by a slow dependency
## Symptoms
Orders p95 latency and queue depth rise while a downstream dependency has slow responses or timeout retries.
## Diagnosis
Compare orders and dependency latency by service. Check retry counts and trace IDs to identify whether payments or inventory is the source.
## Remediation
Enable the circuit breaker for the confirmed slow dependency and preserve a clear fallback response. Scale out downstream only if capacity is the cause.
## Verification
Orders queue depth should drain and latency should recover without a retry storm.
## Avoid
Do not add retries without backoff; they increase pressure on a dependency that is already slow.
