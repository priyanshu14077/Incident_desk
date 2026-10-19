# Runbook: reschedule a batch job that starves the shared database

Use when shared database CPU or query latency climbs after a scheduled job starts, and app queries slow down or time out.

## 1. Confirm
- A scheduled job started on the shared database shortly before the slowdown.
- Database CPU is high and the database names the job as its top consumer.

## 2. Stop the job
- Pause or cancel the running job; it can be rerun safely later.

## 3. Reschedule
- Move the job back to its off-peak window (02:00) and get the owning team's agreement.
- Consider running it against a read replica.

## 4. Verify
- Database CPU and query latency return to baseline; app timeouts stop.
