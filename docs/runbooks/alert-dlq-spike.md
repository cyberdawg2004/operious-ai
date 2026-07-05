# Alert: dlq_spike

## What fires it

`AlertEvaluator._check_dlq_spike` fires when the increase in `dead_letter_tasks` rows created in the last hour exceeds `ALERT_DLQ_SPIKE_THRESHOLD` (default: **5** new records per evaluation cycle). Cooldown: 600 s. Severity: **critical**.

The evaluator queries `SELECT COUNT(*) FROM dead_letter_tasks WHERE created_at > NOW() - INTERVAL '1 hour'` through the owner session (cross-tenant, bypasses RLS), compares against a baseline stored in Redis key `alert:dlq_baseline`, and fires if `delta >= ALERT_DLQ_SPIKE_THRESHOLD`. The baseline is updated each evaluation cycle.

## What it means

More than 5 additional tasks have dead-lettered in the last evaluation window. This is a critical signal because DLQ entries represent tasks that exhausted all retries and will not be reprocessed without operator intervention. A spike may indicate a provider outage, application regression, data corruption, or a worker crash loop.

## Immediate triage

1. Confirm backend health and current DLQ state.

   ```bash
   curl -sS https://operious-ai-imad.fly.dev/api/v1/health | python3 -m json.tool | grep '"status"'
   ```

2. Inspect the first 50 DLQ records grouped by error class.

   ```bash
   curl -sS "https://operious-ai-imad.fly.dev/api/v1/operations/dead-letters?limit=50" \
     -H "Authorization: Bearer ${OPERIOUS_OPERATOR_TOKEN:?}" | \
     python3 -m json.tool | grep -E '"id"|"error_class"|"task_name"|"created_at"'
   ```

3. Check which queue is contributing the most to DLQ by reviewing task names.

   ```bash
   curl -sS "https://operious-ai-imad.fly.dev/api/v1/operations/dead-letters?limit=100" \
     -H "Authorization: Bearer ${OPERIOUS_OPERATOR_TOKEN:?}" | \
     python3 -c "
   import json, sys
   from collections import Counter
   items = json.load(sys.stdin).get('items', [])
   c = Counter(i.get('error_class','?') for i in items)
   print(json.dumps(dict(c.most_common(10)), indent=2))
   "
   ```

4. Check for a provider outage if `error_class` is `PROVIDER_429` or `PROVIDER_5XX`.

   ```bash
   curl -sS https://status.anthropic.com | head -5
   ```

5. Tail `worker_diagnostic` and `worker_maintenance` logs to see what is actively failing.

   ```bash
   timeout 30s fly logs --app operious-ai-imad | grep -E "worker_diagnostic|worker_maintenance|dead_letter"
   ```

## Root causes

- **Provider outage**: Anthropic 429/5XX exhausts retries and dead-letters tasks in bulk. Most common scenario for a sudden DLQ spike.
- **Application regression**: a code deploy introduced a bug that causes `diagnostic_agent_task` or related tasks to fail on every attempt.
- **Data corruption or bad input**: a batch of tickets with malformed content fails consistently with the same application-level error class.
- **Worker crash loop**: `worker_diagnostic` or `worker_maintenance` crashes on startup, re-queuing tasks that immediately fail again.
- **Schema mismatch after migration**: a failed Alembic migration leaves the DB in a state that causes serialization errors for all new task payloads.
- **Redis DLQ baseline reset**: if Redis restarts and `alert:dlq_baseline` is cleared, the next cycle will spike delta to the full 1-hour count.

## Resolution

1. Identify the error class. If it is `PROVIDER_429` or `PROVIDER_5XX`, follow `docs/runbooks/provider-outage.md` first — do not replay DLQ until the provider is stable.

2. If the error class is application-specific, check the Sentry event for the root exception. Do not replay until the application fix is deployed.

3. After the root cause is resolved, replay DLQ records one at a time following `docs/runbooks/dlq-replay.md`.

   ```bash
   DLQ_ID="$(curl -sS "https://operious-ai-imad.fly.dev/api/v1/operations/dead-letters?limit=1" \
     -H "Authorization: Bearer ${OPERIOUS_OPERATOR_TOKEN:?}" | \
     python3 -c 'import json, sys; items=json.load(sys.stdin).get("items",[]); print(items[0]["id"] if items else "")')"
   test -n "$DLQ_ID"
   curl -sS -X POST \
     "https://operious-ai-imad.fly.dev/api/v1/operations/dead-letters/$DLQ_ID/replay" \
     -H "Authorization: Bearer ${OPERIOUS_OPERATOR_TOKEN:?}" | python3 -m json.tool
   ```

4. If `alert:dlq_baseline` in Redis was reset (e.g., Redis restart), the next alert will be a false positive. Verify by checking the Redis baseline manually if you have Redis access.

## Escalation

- **Page immediately**: any DLQ spike above 5 is critical by design. Confirm the error class before escalating further.
- **Full incident response** if: `error_class` is mixed (suggests multiple failure modes), DLQ is growing faster than 20 new records per cycle, or `worker_diagnostic` is crash-looping.
- **Defer replay** until root cause is confirmed and fixed. Do not run bulk replay as a first response.
- Cooldown is 600 s (10 minutes). If the alert fires again within 10 minutes after the baseline resets, the root cause is still active.
