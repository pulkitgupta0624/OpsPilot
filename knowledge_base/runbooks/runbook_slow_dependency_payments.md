---
doc_id: rb_slow_dependency_payments
doc_type: runbook
service: payments
fault_type: slow_dependency
severity: sev2
date: 2025-04-08
status: verified
tags: [dependency, authorization, timeout]
correct_actions: [enable_circuit_breaker]
---
# Runbook: Payments authorization dependency latency
## Symptoms
Charge requests wait on an authorization dependency; payment p95 latency, timeout errors, and queued work increase.
## Diagnosis
Check dependency health and request traces, then compare local CPU and database pool metrics. A healthy local pool with slow remote replies points downstream.
## Remediation
Enable the circuit breaker for the affected dependency and return the approved retryable status to callers.
## Verification
Verify active requests are bounded, retry volume falls, and successful authorization latency returns to its SLO.
## Avoid
Do not treat dependency latency as database-pool exhaustion without matching pool evidence.
