---
doc_id: svc_inventory_overview
doc_type: service_doc
service: inventory
status: verified
tags: [architecture, dependencies, slo, operations]
owner: stock-platform
slo: p95 reservation latency below 250 ms and reservation conflict rate below 0.5 percent
---
# Inventory service operations guide
## Responsibility
Inventory answers availability checks and creates stock reservations for orders. Reservation state must remain consistent with the stock ledger.
## Dependencies
Orders calls inventory synchronously. Inventory uses its own database and may read supplier or catalog dependencies; trace the slow span before treating a caller symptom as a local fault.
## Operational signals
Monitor reservation latency and errors, queue depth, database pool saturation, memory trend, disk capacity, snapshot freshness, and deployment version.
## Deployment and ownership
Stock Platform owns the service. Use rollback for release-correlated errors, bounded pools for database contention, and the circuit breaker for slow remote dependencies.
## Recovery notes
Do not delete active reservations to recover memory or disk. Verify reservation writes and snapshot freshness after any corrective action.
