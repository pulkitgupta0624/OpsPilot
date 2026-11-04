---
doc_id: pm_20250915_payments_trace_growth
doc_type: postmortem
service: payments
fault_type: disk_full
severity: sev1
date: 2025-09-15
status: verified
tags: [disk, trace, audit]
---
# Payment trace spool consumed reserved disk space
## Impact
Payment journal writes began failing as a trace spool shared the same volume and filled its reserve.
## Timeline
07:18 UTC trace export paused; 07:25 disk use hit 99 percent; 07:31 trace files were moved to approved storage and journal writes recovered.
## Root cause
A tracing exporter retried delivery indefinitely and retained every batch locally.
## Contributing factors
Tracing and durable payment evidence shared one filesystem, and spool size had no cap.
## Fix and verification
Reclaimed eligible trace data without deleting audit records, set a spool limit, and confirmed journal writes and reconciliation succeeded.
## Lessons
Isolate observability storage from durable payment data and cap retry buffers.
