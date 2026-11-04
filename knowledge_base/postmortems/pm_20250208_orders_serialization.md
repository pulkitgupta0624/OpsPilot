---
doc_id: pm_20250208_orders_serialization
doc_type: postmortem
service: orders
fault_type: bad_deployment
severity: sev1
date: 2025-02-08
status: verified
tags: [deployment, serialization, rollback]
---
# Orders release regressed response serialization
## Impact
Order creation errors rose after a release; accepted orders remained durable and could be reconciled.
## Timeline
08:30 UTC canary began; 08:34 the error rate stepped up; 08:39 the release was rolled back.
## Root cause
The new response schema serialized a nullable address as a required nested field.
## Contributing factors
The canary covered only complete addresses and the rollout alert was grouped by service rather than version.
## Fix and verification
Rolled back orders and added nullable-field examples to contract checks. Error rate fell on the prior version.
## Lessons
Tie error-step alerts to deployment metadata and exercise optional fields before rollout.
