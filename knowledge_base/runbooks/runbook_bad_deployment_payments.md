---
doc_id: rb_bad_deployment_payments
doc_type: runbook
service: payments
fault_type: bad_deployment
severity: sev1
date: 2025-04-11
status: verified
tags: [deployment, rollback, charge-errors]
correct_actions: [rollback_deployment]
---
# Runbook: Payments release regression
## Symptoms
Charge failures increase immediately after a release, often with a new validation or serialization exception.
## Diagnosis
Match the first affected trace and app version to the rollout record. Check if the database pool remains healthy.
## Remediation
Rollback payments to the previous known-good version. Keep charge retries idempotent and stop further rollout.
## Verification
Confirm version rollback, stable charge error rate, and successful reconciliation of any pending payment attempts.
## Avoid
Do not increase the database pool when the error step aligns with a code deployment and pool utilization is normal.
