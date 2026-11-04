---
doc_id: svc_payments_overview
doc_type: service_doc
service: payments
status: verified
tags: [architecture, dependencies, slo, operations]
owner: money-movement
slo: p95 authorization latency below 500 ms and duplicate charge count equal to zero
---
# Payments service operations guide
## Responsibility
Payments authorizes charges, persists the payment journal, and supports reconciliation. It owns its connection pool and idempotency boundary.
## Dependencies
Orders calls payments synchronously. Payments also relies on its database and external authorization or token providers; distinguish these paths with traces and pool metrics.
## Operational signals
Review charge success, authorization latency, connection in-use versus pool size, acquire timeout count, disk capacity, journal write errors, and active version.
## Deployment and ownership
Money Movement owns the service. Payment retries must preserve idempotency. Roll back a release-linked error step; increase the pool only after checking shared database capacity.
## Recovery notes
Protect the journal and audit trail during disk cleanup. Verify reconciliation and charge status before replaying any uncertain request.
