---
doc_id: pm_20250402_payments_heap_growth
doc_type: postmortem
service: payments
fault_type: memory_leak
severity: sev2
date: 2025-04-02
status: verified
tags: [heap, worker, batch]
---
# Payments batch workers retained completed charge records
## Impact
Charge completion slowed near the end of a settlement batch; idempotent retries prevented duplicate captures.
## Timeline
13:00 UTC batch began; 13:28 memory and GC pause time rose; 13:36 workers were drained and restarted.
## Root cause
Completed charge records remained referenced by a batch-local diagnostic list until the entire batch ended.
## Contributing factors
Worker memory alerts were configured on an absolute value and missed the sustained upward trend.
## Fix and verification
Restarted the affected worker pool and released records after each checkpoint. A repeated settlement completed with stable heap usage.
## Lessons
Bound diagnostic buffers and monitor memory per worker across batch boundaries.
