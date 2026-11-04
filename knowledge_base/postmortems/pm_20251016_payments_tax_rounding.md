---
doc_id: pm_20251016_payments_tax_rounding
doc_type: postmortem
service: payments
fault_type: bad_deployment
severity: sev2
date: 2025-10-16
status: verified
tags: [deployment, rounding, payment-validation]
---
# Payment release changed tax rounding at the authorization boundary
## Impact
A subset of charges failed amount validation; accepted transactions remained available for reconciliation.
## Timeline
16:20 UTC rollout began; 16:24 amount-mismatch errors appeared; 16:31 rollback restored the previous calculation.
## Root cause
The release rounded a decimal amount before applying tax, unlike the established currency-specific order.
## Contributing factors
The test set did not include low-value transactions near a rounding boundary.
## Fix and verification
Rolled back and added boundary-value cases for each supported currency. Authorization amounts matched the ledger after redeployment.
## Lessons
Check release versions and payload deltas before assuming pool or dependency pressure.
