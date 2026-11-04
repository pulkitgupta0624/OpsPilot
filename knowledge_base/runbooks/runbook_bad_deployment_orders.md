---
doc_id: rb_bad_deployment_orders
doc_type: runbook
service: orders
fault_type: bad_deployment
severity: sev1
date: 2025-04-10
status: verified
tags: [deployment, rollback, error-rate]
correct_actions: [rollback_deployment]
---
# Runbook: Orders regression after deployment
## Symptoms
Orders error rate steps up just after a version change; new exception templates or latency shifts appear across requests.
## Diagnosis
Compare the deployment timestamp and app version with the start of the error step. Rule out an unrelated dependency incident before rollback.
## Remediation
Rollback orders to the last known-good version and pause further rollout until the change is reviewed.
## Verification
Confirm the old version is active and error rate and p95 latency return toward baseline.
## Avoid
Do not restart repeatedly on the faulty version; that does not remove the regression.
