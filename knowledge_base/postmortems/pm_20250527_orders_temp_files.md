---
doc_id: pm_20250527_orders_temp_files
doc_type: postmortem
service: orders
fault_type: disk_full
severity: sev2
date: 2025-05-27
status: verified
tags: [disk, temporary-files, export]
---
# Orders export left temporary files on the service volume
## Impact
Order export writes and several request logs failed when the volume reached capacity.
## Timeline
20:00 UTC export started; 20:34 disk usage passed 90 percent; 20:42 approved temporary files were removed and the export was paused.
## Root cause
The export process left partial files after client cancellation and did not enforce a workspace quota.
## Contributing factors
The cleanup job ran daily, too slowly for the export's peak growth rate.
## Fix and verification
Removed only incomplete temporary exports, added atomic cleanup on cancellation, and verified durable order data was intact.
## Lessons
Track temporary-file growth separately and never delete durable order records to reclaim space.
