---
doc_id: pm_20250503_orders_payment_latency
doc_type: postmortem
service: orders
fault_type: slow_dependency
severity: sev2
date: 2025-05-03
status: verified
tags: [payments, upstream, retries]
---
# Checkout latency traced to payment authorization
## Impact
Orders p95 latency and queue depth increased while payment authorization responses slowed.
## Timeline
10:05 UTC payment timeouts appeared; 10:09 orders retries climbed; 10:14 a circuit breaker limited new calls.
## Root cause
Orders held request workers while waiting for payment authorization during a payment-provider slowdown.
## Contributing factors
The orders alert grouped downstream latency with local CPU, making the first diagnosis ambiguous.
## Fix and verification
Enabled the payments breaker and returned a retryable response with jittered client retry. Orders queue drained as provider latency improved.
## Lessons
Use trace spans to distinguish a caller symptom from the root-cause service.
