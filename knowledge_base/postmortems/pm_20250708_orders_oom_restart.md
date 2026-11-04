---
doc_id: pm_20250708_orders_oom_restart
doc_type: postmortem
service: orders
fault_type: memory_leak
severity: sev1
date: 2025-07-08
status: verified
tags: [out-of-memory, restart, request-context]
---
# Orders workers restarted after request-context retention
## Impact
Two orders workers restarted at the traffic peak and checkout errors briefly increased.
## Timeline
17:02 UTC memory crossed its normal band; 17:16 the first OOM restart occurred; 17:24 traffic was drained and workers restarted.
## Root cause
An asynchronous request context retained a full cart object after response completion.
## Contributing factors
Restart count was reviewed after the event rather than correlated with memory growth in the alert.
## Fix and verification
Restarted workers and released the context in the response-finalization hook. Load replay showed flat memory and no further restarts.
## Lessons
Include restart deltas in incident evidence and test cleanup on cancelled requests.
