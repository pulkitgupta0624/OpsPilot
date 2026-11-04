---
doc_id: pm_20251220_inventory_feature_flag
doc_type: postmortem
service: inventory
fault_type: bad_deployment
severity: sev3
date: 2025-12-20
status: verified
tags: [deployment, feature-flag, reservation-errors]
---
# Inventory feature flag enabled an incomplete reservation path
## Impact
Reservation conflicts increased for items assigned to the new allocation path.
## Timeline
12:01 UTC flag expanded; 12:06 conflict errors rose; 12:13 rollout was reverted to the previous release and flag state.
## Root cause
The new path treated a missing warehouse preference as a hard validation error.
## Contributing factors
Flag changes and application releases were reviewed separately, obscuring their combined effect.
## Fix and verification
Reverted the deployment and flag. A guarded fallback was added and verified with items lacking a preference.
## Lessons
Record flag changes in deployment history and include null or incomplete metadata in canary scenarios.
