---
doc_id: pm_20250414_payments_validation
doc_type: postmortem
service: payments
fault_type: bad_deployment
severity: sev1
date: 2025-04-14
status: verified
tags: [deployment, validation, charge-errors]
---
# Payment validation change rejected valid currency codes
## Impact
Charges for a small set of supported currencies failed validation for seven minutes.
## Timeline
11:12 UTC release reached payments; 11:16 currency errors spiked; 11:19 the previous version was restored.
## Root cause
A stricter validator used a stale currency allowlist that omitted two active markets.
## Contributing factors
The canary dataset contained only the three highest-volume currencies.
## Fix and verification
Rolled back and expanded contract tests to all supported currency codes. Charge success returned to its prior level.
## Lessons
When errors rise immediately after a version change, compare version and exception details before changing infrastructure.
