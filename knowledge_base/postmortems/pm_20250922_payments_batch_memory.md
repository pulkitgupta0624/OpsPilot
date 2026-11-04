---
doc_id: pm_20250922_payments_batch_memory
doc_type: postmortem
service: payments
fault_type: memory_leak
severity: sev2
date: 2025-09-22
status: verified
tags: [webhook, payload, heap]
---
# Payment webhook parser retained large payloads
## Impact
Webhook acknowledgement latency rose during a partner retry wave; charge processing remained available.
## Timeline
11:40 UTC payload volume increased; 12:05 heap trend accelerated; 12:17 the parser workers were restarted.
## Root cause
The parser stored raw request bodies in an in-memory retry map after successful validation.
## Contributing factors
Payload-size limits existed at the gateway but were not applied to the retry map.
## Fix and verification
Restarted workers, removed successful payloads from the map, and replayed redacted samples with a capped buffer.
## Lessons
Store retry references rather than entire payloads and set a retention limit for every in-memory queue.
