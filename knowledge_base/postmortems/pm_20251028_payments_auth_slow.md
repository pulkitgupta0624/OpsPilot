---
doc_id: pm_20251028_payments_auth_slow
doc_type: postmortem
service: payments
fault_type: slow_dependency
severity: sev2
date: 2025-10-28
status: verified
tags: [token-provider, authorization, timeout]
---
# Payment token provider latency increased authorization time
## Impact
Authorizations timed out more often for eleven minutes, while the local database pool remained below its limit.
## Timeline
04:10 UTC token refresh latency rose; 04:14 charge p95 crossed its SLO; 04:19 the provider breaker reduced pending calls.
## Root cause
The external token provider served refresh responses slowly during a maintenance window.
## Contributing factors
Payment retries used the same timeout as the original call, and local pool saturation was initially suspected.
## Fix and verification
Enabled the token-provider circuit breaker and separated refresh work from charge transactions. Pool utilization stayed normal after recovery.
## Lessons
Use dependency-specific evidence; a charge timeout does not by itself prove a database pool fault.
