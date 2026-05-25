# Tenant Isolation Incident Response

## Overview
Use this runbook for any suspected cross-tenant data exposure in Operious AI, including reports that Tenant A can see Tenant B data in Command Center at https://app.operious.com or through the backend at https://operious-ai-imad.fly.dev. This is the highest-severity operational incident: even a suspected isolation breach must be treated as confirmed until RLS-enforced evidence proves otherwise. Production anchors are Fly app `operious-ai-imad` in Singapore, marketing at https://www.operious.com, Neon Postgres roles `operious_app` with `BYPASSRLS=False` and `neondb_owner`, Alembic head `0039_dlq_replay_cols`, Upstash Redis via `REDIS_URL` or `UPSTASH_REDIS_URL`, Auth0 domain `operious-dev.uk.auth0.com`, Sentry, and branch `phase-2-2-stabilized`.

## Trigger Conditions
- A user reports that one tenant can see another tenant's sessions, events, executions, DLQ records, quota records, or SOP data.
- Command Center shows cross-tenant data while authenticated through Auth0 tenant domain `operious-dev.uk.auth0.com`.
- Sentry emits an alert or exception indicating RLS failure, tenant scope mismatch, `tenant_axis_missing`, or unexpected cross-tenant access.
- A production query as `operious_app` returns rows for a tenant other than `app.current_tenant_id`.
- The production app role `operious_app` has `rolbypassrls=True`.

## Immediate Assessment (< 5 minutes)
Do not modify any data. Screenshot or record exactly what was observed, including URL, tenant IDs, visible record IDs, Auth0 user, and local timestamp.

```bash
date -u
```

Expected: UTC timestamp for the incident record. If possible, also capture the browser timestamp from Command Center.

```bash
fly ssh console --app operious-ai-imad \
  --command "python -c \"
import asyncio, asyncpg, os
async def check():
    url = os.environ['DATABASE_URL'].replace(
        'postgresql+asyncpg://', 'postgresql://')
    conn = await asyncpg.connect(url)
    r = await conn.fetchrow(
        'SELECT current_user, '
        '(SELECT rolbypassrls FROM pg_roles '
        ' WHERE rolname = current_user) as bypass')
    print(f'user={r[0]} bypassrls={r[1]}')
asyncio.run(check())
\""
```

Expected:

```text
user=operious_app bypassrls=False
```

If output is `bypassrls=True`, escalate immediately. The production app role has gained `BYPASSRLS` unexpectedly.

```bash
curl -sS https://operious-ai-imad.fly.dev/api/v1/health | python3 -m json.tool | grep '"status"'
```

Expected: the backend is reachable. Health does not prove tenant isolation, but confirms whether API checks are possible.

```bash
curl -sS https://operious-ai-imad.fly.dev/api/v1/session/sessions \
  -H "X-Tenant-ID: anker-pilot" \
  -H "Authorization: Bearer ${OPERIOUS_OPERATOR_TOKEN:?set OPERIOUS_OPERATOR_TOKEN to an Auth0 operator token from https://app.operious.com}" | \
  python3 -m json.tool | grep -E '"total"|"tenant_id"'
```

Expected: records visible through the API belong to `anker-pilot`. If another tenant ID appears, treat the incident as confirmed and continue without changing data.

## Impact Scope
| Condition | Broken | Still Works | Affected Users |
| --- | --- | --- | --- |
| Suspected frontend tenant mix-up only | Command Center may display stale or wrong tenant data. | RLS may still protect Neon Postgres; backend health may be normal. | User or operator session that observed the wrong data. |
| Missing or disabled RLS on a table | Direct database access through `operious_app` may expose rows outside `app.current_tenant_id`. | Unaffected tables with ENABLE and FORCE RLS still isolate data. | Any tenant with rows in the affected table. |
| `operious_app` has `BYPASSRLS=True` | RLS is bypassed for the application role across production reads. | Owner role `neondb_owner` can still repair role attributes. | All tenants, including `anker-pilot`. |

## Recovery Steps
1. Preserve evidence before changing anything.

   Command:

   ```bash
   date -u
   ```

   Expected: a UTC timestamp you can paste into the incident report beside screenshots, tenant IDs, record IDs, and Auth0 principal.

   If it does not work: write down the local time and timezone manually. Continue to preserve evidence.

2. Verify the production app role is not bypassing RLS.

   Command:

   ```bash
   fly ssh console --app operious-ai-imad \
     --command "python -c \"
import asyncio, asyncpg, os
async def check():
    url = os.environ['DATABASE_URL'].replace(
        'postgresql+asyncpg://', 'postgresql://')
    conn = await asyncpg.connect(url)
    r = await conn.fetchrow(
        'SELECT current_user, '
        '(SELECT rolbypassrls FROM pg_roles '
        ' WHERE rolname = current_user) as bypass')
    print(f'user={r[0]} bypassrls={r[1]}')
asyncio.run(check())
\""
   ```

   Expected: `user=operious_app bypassrls=False`.

   If it does not work: if SSH fails, use Fly dashboard console for `operious-ai-imad`. If output shows `bypassrls=True`, go to Step 6 immediately.

3. Confirm RLS-enforced visibility as the restricted app role in Neon SQL Editor.

   Command in Neon SQL Editor connected as `operious_app`:

   ```sql
   SELECT set_config('app.current_tenant_id', 'anker-pilot', true);
   SELECT tenant_id, count(*) AS rows_visible
   FROM public.operational_sessions
   GROUP BY tenant_id
   ORDER BY tenant_id;
   ```

   Expected: only `anker-pilot` rows are visible. If another tenant ID appears, RLS is not enforcing correctly for `public.operational_sessions`.

   If it does not work: confirm the SQL Editor connection is using `operious_app`, not `neondb_owner`. Owner role bypass behavior can invalidate this diagnostic.

4. Check high-risk tenant-scoped tables for RLS and FORCE RLS status as `neondb_owner`.

   Command in Neon SQL Editor connected as `neondb_owner`:

   ```sql
   SELECT c.relname AS table_name, c.relrowsecurity AS rls_enabled, c.relforcerowsecurity AS force_rls
   FROM pg_class c
   JOIN pg_namespace n ON n.oid = c.relnamespace
   WHERE n.nspname = 'public'
     AND c.relname IN (
       'operational_sessions',
       'session_events',
       'execution_records',
       'execution_attempts',
       'dead_letter_tasks',
       'provider_quota_records',
       'provider_circuit_states'
     )
   ORDER BY c.relname;
   ```

   Expected: tenant-scoped tables show `rls_enabled=true`. Tables hardened by PR_T4 and PR_T7, including `provider_quota_records` and `provider_circuit_states`, should show `force_rls=true`.

   If it does not work: stop and escalate to the database owner path. Do not run broad data-changing SQL.

5. If RLS is intact but the frontend showed wrong data, isolate the browser/session path.

   Command:

   ```bash
   curl -sS https://operious-ai-imad.fly.dev/api/v1/session/sessions \
     -H "X-Tenant-ID: anker-pilot" \
     -H "Authorization: Bearer ${OPERIOUS_OPERATOR_TOKEN:?set OPERIOUS_OPERATOR_TOKEN to an Auth0 operator token from https://app.operious.com}" | \
     python3 -m json.tool | grep -E '"total"|"tenant_id"'
   ```

   Expected: API results are scoped to `anker-pilot`. Clear browser cache, re-authenticate through https://app.operious.com, and retest while checking the `X-Tenant-ID` request header in browser network inspector.

   If it does not work: if API results show another tenant, this is not just frontend cache. Continue with RLS repair.

6. If `operious_app` has `BYPASSRLS=True`, remove it immediately as `neondb_owner`.

   Command in Neon SQL Editor connected as `neondb_owner`:

   ```sql
   ALTER ROLE operious_app NOBYPASSRLS;
   SELECT rolname, rolbypassrls
   FROM pg_roles
   WHERE rolname = 'operious_app';
   ```

   Expected: `operious_app` returns `rolbypassrls=false`.

   If it does not work: stop the backend app from serving requests until the role can be repaired. Use `fly scale count 0 --process-group web --app operious-ai-imad --yes` only if the exposure is confirmed and active.

7. If RLS is missing on a production table, enable and force RLS as `neondb_owner`.

   Command in Neon SQL Editor connected as `neondb_owner`:

   ```sql
   ALTER TABLE public.operational_sessions ENABLE ROW LEVEL SECURITY;
   ALTER TABLE public.operational_sessions FORCE ROW LEVEL SECURITY;
   ALTER TABLE public.execution_records ENABLE ROW LEVEL SECURITY;
   ALTER TABLE public.execution_records FORCE ROW LEVEL SECURITY;
   ALTER TABLE public.dead_letter_tasks ENABLE ROW LEVEL SECURITY;
   ALTER TABLE public.dead_letter_tasks FORCE ROW LEVEL SECURITY;
   ```

   Expected: affected tables have RLS enabled immediately. Re-run Step 3 as `operious_app` before reopening normal operations.

   If it does not work: do not improvise a policy during the incident unless the missing policy is fully understood. Keep access restricted and fix forward with a reviewed migration.

## Verification
```bash
fly ssh console --app operious-ai-imad \
  --command "python -c \"
import asyncio, asyncpg, os
async def check():
    url = os.environ['DATABASE_URL'].replace(
        'postgresql+asyncpg://', 'postgresql://')
    conn = await asyncpg.connect(url)
    r = await conn.fetchrow(
        'SELECT current_user, '
        '(SELECT rolbypassrls FROM pg_roles '
        ' WHERE rolname = current_user) as bypass')
    print(f'user={r[0]} bypassrls={r[1]}')
asyncio.run(check())
\""
```

Expected:

```text
user=operious_app bypassrls=False
```

Run in Neon SQL Editor as `operious_app`:

```sql
SELECT set_config('app.current_tenant_id', 'anker-pilot', true);
SELECT tenant_id, count(*) AS rows_visible
FROM public.operational_sessions
GROUP BY tenant_id
ORDER BY tenant_id;
```

Expected: only `anker-pilot` is visible for this tenant context.

```bash
curl -sS https://operious-ai-imad.fly.dev/api/v1/session/sessions \
  -H "X-Tenant-ID: anker-pilot" \
  -H "Authorization: Bearer ${OPERIOUS_OPERATOR_TOKEN:?set OPERIOUS_OPERATOR_TOKEN to an Auth0 operator token from https://app.operious.com}" | \
  python3 -m json.tool | grep '"total"'
```

Expected: sessions return for `anker-pilot` without cross-tenant rows or `tenant_axis_missing` errors.

## Post-Incident Actions
- File a full incident report even if the suspected breach is disproven. Include screenshots, tenant IDs, record IDs, exact queries, exact results, Auth0 principal, and timestamps.
- State explicitly whether the breach was confirmed or denied by RLS-enforced queries as `operious_app`.
- If RLS was repaired manually, write a reviewed migration that makes the fix durable and add a regression test for the affected table.
- Audit recent deploys, migrations, and role changes for anything that could alter `operious_app`, `neondb_owner`, or `app.current_tenant_id` behavior.
- Continue monitoring Sentry, Command Center, and tenant-scoped API responses for at least 24 hours.
