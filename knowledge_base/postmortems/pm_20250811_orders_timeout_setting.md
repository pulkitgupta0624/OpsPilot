---
doc_id: pm_20250811_orders_timeout_setting
doc_type: postmortem
service: orders
fault_type: bad_deployment
severity: sev2
date: 2025-08-11
status: verified
tags: [deployment, timeout, config]
---
# Orders deploy shortened the dependency deadline accidentally
## Impact
Orders returned timeout errors despite downstream services remaining within their normal latency band.
## Timeline
05:45 UTC configuration rollout started; 05:50 timeout errors increased; 05:57 rollback restored the previous setting.
## Root cause
A seconds-to-milliseconds conversion was applied twice, reducing the dependency deadline by a factor of one thousand.
## Contributing factors
Configuration was not included in the canary comparison and the timeout metric lacked the active version label.
## Fix and verification
Rolled back and added unit checks for time units. A staged rollout preserved the expected deadline.
## Lessons
An abrupt error step with healthy dependencies can indicate a configuration regression.
