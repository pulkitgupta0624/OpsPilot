---
doc_id: svc_orders_overview
doc_type: service_doc
service: orders
status: verified
tags: [architecture, dependencies, slo, operations]
owner: commerce-platform
slo: p95 latency below 300 ms and request error rate below 1 percent
---
# Orders service operations guide
## Responsibility
Orders is the customer-facing entry point. It validates carts, coordinates payment authorization, and asks inventory to reserve stock.
## Dependencies
The synchronous call graph is orders to payments and orders to inventory. A slow dependency can raise orders latency while local CPU and database pool remain healthy.
## Operational signals
Watch request rate, p95 latency, error rate, queue depth, memory slope, restart count, database pool utilization, and active app version together.
## Deployment and ownership
Commerce Platform owns the service. Compare errors with deployment history before changing infrastructure; rollback a release regression, and keep order writes idempotent.
## Recovery notes
Protect downstream calls with bounded timeouts and circuit breakers. Verify successful order persistence and reservation reconciliation after recovery.
