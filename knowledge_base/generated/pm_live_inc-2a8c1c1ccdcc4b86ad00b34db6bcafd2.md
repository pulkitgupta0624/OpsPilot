---
doc_id: pm_live_inc-2a8c1c1ccdcc4b86ad00b34db6bcafd2
doc_type: postmortem
service: payments
fault_type: db_pool_exhaustion
severity: sev2
date: '2026-11-03'
status: unverified
title: Metrics anomaly for payments (rolling_zscore)
---

# Metrics anomaly for payments (rolling_zscore)

## Incident

- ID: `inc-2a8c1c1ccdcc4b86ad00b34db6bcafd2`
- Service: `payments`
- Fault type: `db_pool_exhaustion`
- Reported at: `2026-11-03T18:09:58.272318+00:00`

## Root cause

Initial classification from alert features and service symptoms.

## Impact

The affected simulated service showed anomalous telemetry until remediation.

## Resolution

Applied increase_db_pool; All recovery signals passed three consecutive live samples..

## Lessons

- Keep alert evidence and remediation approval attached to the incident.

## References

- [rb_db_pool_exhaustion_payments | Runbook: Payments database pool exhaustion > Diagnosis]
- [rb_db_pool_exhaustion_payments | Runbook: Payments database pool exhaustion > Symptoms]
- [pm_20250217_payments_pool_wait | Payment authorization transactions exhausted the pool > Impact]
- [pm_20250217_payments_pool_wait | Payment authorization transactions exhausted the pool > Timeline]
- [rb_db_pool_exhaustion_payments | Runbook: Payments database pool exhaustion > Verification]

