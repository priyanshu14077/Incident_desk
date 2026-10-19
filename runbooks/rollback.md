# Runbook: roll back a bad deploy

Use when errors or latency start within minutes of a deploy to the affected service.

## 1. Confirm the deploy is the trigger
- The deploy time comes before the first error, with no other change to that service in between.
- The errors name the deployed service, or come from callers of it.

## 2. Roll back
- Redeploy the previous version (for example `payments v2.4.0`) through the release pipeline.
- Do not hot-patch config in production; roll back the whole release.

## 3. Verify
- Error rate and p95 latency back inside their baseline within 10 minutes.
- For DB pool problems: `db_connections` back to its normal level and no "pool exhausted" errors.

## 4. Follow up
- Freeze further deploys of the service until the root cause is understood.
- Open a post-incident review for the release.
