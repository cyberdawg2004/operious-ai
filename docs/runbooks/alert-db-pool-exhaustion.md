# Alert: db_pool_exhaustion

## What fires it

`AlertEvaluator._check_db_pool` fires when the DB connection pool utilisation ratio meets or exceeds `ALERT_DB_POOL_UTILIZATION` (default: **0.9**, i.e. 90%). Cooldown: 60 s. Severity: **critical**.

Utilisation is calculated as `checked_out / (pool.size() + pool.overflow())`. The pool capacity is `DB_POOL_SIZE=10` + `DB_MAX_OVERFLOW=5` = 15 connections maximum. The alert fires when 14 or more of the 15 connections are checked out simultaneously. The check is skipped when `DB_USE_NULLPOOL=True` (which is the case for all Celery worker process groups in production — only the `web` process uses a real connection pool).

This alert only fires from the `web` process since workers run with `DB_USE_NULLPOOL=true`.

## What it means

The FastAPI web process has nearly all of its 15 Postgres connections checked out and no capacity to serve new requests that require DB access. New API requests needing a DB connection will wait up to `DB_POOL_TIMEOUT=30` seconds before failing with a pool timeout error, manifesting as HTTP 500 or 503 for end users. This is immediately visible as response time spikes in the Command Center at https://app.operious.com.

## Immediate triage

1. Check overall backend health and response time.

   ```bash
   curl -sS -w "\nTotal time: %{time_total}s\n" https://operious-ai-imad.fly.dev/api/v1/health
   ```

2. Check Fly web machine count and status.

   ```bash
   fly status --app operious-ai-imad
   ```

   Expected: `web` process group shows at least 1 running machine. Pool exhaustion is per-machine (each web machine has its own pool of 15 connections).

3. Check Neon Postgres connection count from the DB side.

   ```bash
   fly ssh console --app operious-ai-imad \
     --command "python3 -c \"
   import os, asyncio
   from sqlalchemy.ext.asyncio import create_async_engine
   from sqlalchemy import text

   async def check():
       engine = create_async_engine(os.environ['DATABASE_URL'])
       async with engine.connect() as conn:
           result = await conn.execute(text(
               'SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()'
           ))
           print('active_connections:', result.scalar())
   asyncio.run(check())
   \""
   ```

4. Look for long-running transactions or stuck queries in logs.

   ```bash
   timeout 30s fly logs --app operious-ai-imad | grep -i "web\|pool\|timeout\|connection" | head -40
   ```

5. Check the admission gate DB pool metric.

   ```bash
   curl -sS https://operious-ai-imad.fly.dev/api/v1/health | \
     python3 -m json.tool | grep -A5 '"database"'
   ```

## Root causes

- **Slow API endpoint holding connections open**: a long-running endpoint (e.g., bulk knowledge upload, large tenant query) holds a connection for the full request duration, depleting the pool.
- **Missing `await session.close()` or unclosed sessions**: a code path leaks a session that is not closed at request end, gradually depleting the pool.
- **Database slow due to Neon cold-start or high load**: all requests block on DB responses, keeping connections checked out for longer than usual.
- **Traffic spike to the single `web` machine**: the web machine has `max_machines_running=2`. If auto-start has not yet launched a second machine, a burst of requests can exhaust the pool on a single machine.
- **Large migration or schema operation running concurrently**: Alembic migrations run in a release machine but a manual migration or one-off query via `fly ssh console` might hold open connections.

## Resolution

1. If the pool is transiently exhausted by a traffic spike, scale up the web process.

   ```bash
   fly scale count 2 --process-group web --app operious-ai-imad
   ```

   Each additional web machine gets its own pool of 15 connections.

2. If a specific endpoint is leaking connections, identify and kill it without waiting.

   ```bash
   fly ssh console --app operious-ai-imad \
     --command "python3 -c \"
   import os, asyncio
   from sqlalchemy.ext.asyncio import create_async_engine
   from sqlalchemy import text

   async def check():
       engine = create_async_engine(os.environ['DATABASE_URL'])
       async with engine.connect() as conn:
           result = await conn.execute(text('''
               SELECT pid, usename, application_name, state, query_start, query
               FROM pg_stat_activity
               WHERE datname = current_database()
               AND state != 'idle'
               ORDER BY query_start
           '''))
           for row in result:
               print(dict(row))
   asyncio.run(check())
   \""
   ```

3. If a stuck query is identified, terminate it.

   ```bash
   fly ssh console --app operious-ai-imad \
     --command "python3 -c \"
   import os, asyncio
   from sqlalchemy.ext.asyncio import create_async_engine
   from sqlalchemy import text

   async def kill(pid):
       engine = create_async_engine(os.environ['DATABASE_URL'])
       async with engine.connect() as conn:
           await conn.execute(text('SELECT pg_terminate_backend(:pid)'), {'pid': pid})
   asyncio.run(kill(INSERT_PID_HERE))
   \""
   ```

4. If Neon Postgres is the bottleneck, check the Neon console for high CPU, connection limits, or cold-start events. The `operious_app` role is the runtime user.

5. Reduce `DB_POOL_SIZE` only as a last resort — the alert threshold of 90% means near-full utilisation, not that the pool is correctly sized.

## Escalation

- **Page immediately**: this is a critical alert with a 60-second cooldown. Pool exhaustion causes HTTP request failures visible to all tenants using the Command Center.
- **Escalate to on-call DB lead** if Neon Postgres shows connection limit errors, slow query patterns that cannot be addressed by killing individual queries, or if the pool remains exhausted after scaling web to 2 machines.
- If this alert fires alongside `queue_age_slo_breach` on `diagnostic.normal` or `diagnostic.high`, the diagnostic queue may not be draining because the web health check is also failing — prioritise restoring web DB connectivity first.
