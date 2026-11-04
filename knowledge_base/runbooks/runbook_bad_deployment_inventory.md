---
doc_id: rb_bad_deployment_inventory
doc_type: runbook
service: inventory
fault_type: bad_deployment
severity: sev2
date: 2025-04-12
status: verified
tags: [deployment, rollback, reservation-errors]
correct_actions: [rollback_deployment]
---
# Runbook: Inventory release caused reservation failures
## Symptoms
Reservation errors begin after a version change, with new exception names or an abrupt p95 latency shift.
## Diagnosis
Correlate error onset with deployment history and compare the active version with the last healthy version.
## Remediation
Rollback inventory to the known-good release, preserve reservation idempotency, and hold the deployment pipeline.
## Verification
Check reservations complete, error rate returns to baseline, and the active version matches the rollback target.
## Avoid
Do not clear the reservation queue as a shortcut; that can lose valid customer requests.
