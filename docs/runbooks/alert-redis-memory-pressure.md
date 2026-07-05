# Alert: redis_memory_pressure

## What fires it

`AlertEvaluator._check_redis_memory` fires when the Redis memory utilisation percentage meets or exceeds `ALERT_REDIS_MEMORY_PCT` (default: **85.0%**). Cooldown: 300 s. Severity: **warning**.

The evaluator reads the value from the admission gate's `redis_memory_pct()` method, which queries Redis `INFO memory`. The alert fires if `memory_pct >= 85.0`. The `ADMISSION_REDIS_MEMORY_PCT_WARN` admission-gate threshold is a separate value (default: 70.0%) and `ADMISSION_REDIS_MEMORY_PCT_REJECT` is 90.0% — the alert fires between the warn and reject thresholds.

## What it means

Redis memory is 85% or more consumed. At 90% (`ADMISSION_REDIS_MEMORY_PCT_REJECT`), the admission gate starts rejecting new ticket ingress requests with HTTP 503. The `maxmemory-policy` is required to be `allkeys-lru` — Redis should evict least-recently-used keys when memory is full rather than erroring, but the LRU eviction will begin removing keys that may include admission state, rate-limit counters, webhook freshness nonces, or Celery task results.

## Immediate triage

1. Confirm Redis is reachable and read the raw memory metrics.

   ```bash
   fly ssh console --app operious-ai-imad \
     --command "python3 -c \"
   import os, urllib.request
   url = os.environ.get('REDIS_URL', '')
   # Check via health endpoint instead of direct Redis access
   import json
   req = urllib.request.urlopen('http://localhost:8000/api/v1/health', timeout=5)
   body = json.loads(req.read())
   redis_items = [c for c in body.get('checks', []) if 'redis' in str(c.get('name','')).lower()]
   print(json.dumps(redis_items, indent=2))
   \""
   ```

2. Check admission gate status to see whether rejections have started.

   ```bash
   curl -sS https://operious-ai-imad.fly.dev/api/v1/health | \
     python3 -m json.tool | grep -A5 '"redis"'
   ```

3. Check the Celery result backend and broker queue depths — if Celery result expiry is not cleaning up, results accumulate.

   ```bash
   curl -sS https://operious-ai-imad.fly.dev/api/v1/operations/queue-status \
     -H "Authorization: Bearer ${OPERIOUS_OPERATOR_TOKEN:?}" | \
     python3 -m json.tool | grep -E '"depth"|"status"'
   ```

4. Check whether there is any queue backlog that correlates with a large number of queued Celery task IDs in Redis.

   ```bash
   fly logs --app operious-ai-imad | grep -i "redis\|memory\|evict" | tail -20
   ```

5. Verify Redis `maxmemory-policy` is still `allkeys-lru` (Upstash may reset this on reconnect).

   ```bash
   fly ssh console --app operious-ai-imad \
     --command "python3 -c \"
   import os, redis
   r = redis.from_url(os.environ['REDIS_URL'])
   print(r.config_get('maxmemory-policy'))
   print(r.info('memory'))
   \""
   ```

## Root causes

- **Celery result accumulation**: `CELERY_RESULT_EXPIRES_SECONDS=3600` is the TTL for task results stored in Redis. If a large task burst occurred, results may not have expired yet.
- **Queue depth surge**: a backlog of tasks means more in-flight Celery state is stored in Redis (task IDs, routing keys, retry state).
- **Rate-limit counter explosion**: if `RATE_LIMIT_ENABLED` is true and the tenant is receiving high traffic, the per-IP and per-tenant counters accumulate. Each counter is a Redis key with a 60-second TTL.
- **Webhook nonce accumulation**: each webhook delivery records a freshness nonce in Redis. High webhook throughput creates many short-lived keys.
- **Alert baseline accumulation**: `alert:dlq_baseline` and `alert:cooldown:*` keys are written by the alert evaluator itself. These are small but persistent.
- **Upstash plan limit reached**: if the Operious Upstash plan has a data size cap, Redis may report high utilisation as a percentage of the plan limit rather than available RAM.

## Resolution

1. If `allkeys-lru` is confirmed and Redis eviction is running, reduce memory pressure by waiting for natural key expiry. Most transient keys (Celery results, rate-limit counters, nonces) expire within 60-3600 seconds.

2. If Celery result keys are the primary source of pressure, reduce `CELERY_RESULT_EXPIRES_SECONDS` and restart workers.

   ```bash
   fly secrets set CELERY_RESULT_EXPIRES_SECONDS=600 --app operious-ai-imad
   ```

3. If the Upstash plan limit is reached, consider upgrading the Upstash Redis plan or enabling a separate `QUOTA_REDIS_URL` for quota/rate-limit keys.

4. If queue depth is the driver, resolve the queue backlog first. See `docs/runbooks/queue-backlog.md`.

5. Monitor until utilisation drops below 85%.

   ```bash
   curl -sS https://operious-ai-imad.fly.dev/api/v1/health | python3 -m json.tool | grep -A3 '"redis"'
   ```

## Escalation

- **Investigate before escalating**: the system continues operating at 85% because LRU eviction protects availability. Monitor and investigate root cause.
- **Page on-call** if: utilisation reaches or exceeds 90% (admission gate begins rejecting), Redis begins evicting keys that cause observable functional failures (missing nonces, wrong rate-limit counters), or the health endpoint reports Redis as `critical`.
- At 90% the admission gate fires `ADMISSION_REDIS_MEMORY_PCT_REJECT` and new ticket ingress is refused. At that point the incident is P1 regardless of this alert's warning severity.
