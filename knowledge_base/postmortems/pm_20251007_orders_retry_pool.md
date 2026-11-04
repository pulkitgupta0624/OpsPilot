---
doc_id: pm_20251007_orders_retry_pool
doc_type: postmortem
service: orders
fault_type: db_pool_exhaustion
severity: sev2
date: 2025-10-07
status: verified
tags: [retry-storm, checkout, connection-pool]
---
# Checkout retries amplified database connection pressure
## Impact
Orders pool use stayed at capacity and checkout error rate rose during a brief database slowdown.
## Timeline
12:31 UTC database response time increased; 12:35 retries accelerated; 12:43 backoff was enabled and pool wait declined.
## Root cause
Synchronized retries reopened transactions together and consumed all available connections.
## Contributing factors
Retry policy used a fixed delay and had no jitter; the first alert showed only request errors.
## Fix and verification
Added exponential backoff with jitter and raised pool capacity within budget. A controlled slow-database drill stayed bounded.
## Lessons
Correlate pool occupancy with retry volume before expanding capacity.
