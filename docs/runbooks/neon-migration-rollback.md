# Neon Migration Rollback Procedure

## Overview
Use this runbook only when a production Neon Postgres migration causes an active production error: the app cannot start, queries fail, tenant isolation is broken, or data is corrupted. This is the most dangerous recovery operation in Operious AI because Alembic downgrade changes production schema and may be irreversible after new-format data has been written. Production anchors are Fly app `operious-ai-imad` in Singapore, backend URL https://operious-ai-imad.fly.dev, Command Center at https://app.operious.com, marketing at https://www.operious.com, Neon Postgres roles `operious_app` with `BYPASSRLS=False` and `neondb_owner`, Alembic head `0039_dlq_replay_cols`, Upstash Redis via `REDIS_URL` or `UPSTASH_REDIS_URL`, Auth0 domain `operious-dev.uk.auth0.com`, Sentry, and branch `phase-2-2-stabilized`.

## Trigger Conditions
- A migration deploy completes and `GET /api/v1/health` for https://operious-ai-imad.fly.dev returns non-200 or `critical`.
- Fly logs show application startup or query failures immediately after Alembic migration.
- Sentry error rate spikes with database errors after a migration.
- Neon production queries fail because a column, constraint, FK, index, RLS policy, or table shape changed unexpectedly.
- Current Alembic head differs from expected production head `0039_dlq_replay_cols` and the new head is causing production failure.

## Immediate Assessment (< 5 minutes)
```bash
curl -sS -i https://operious-ai-imad.fly.dev/api/v1/health | head -20
```

Expected: confirms whether the backend is serving. Non-200 after migration means recovery is urgent.

```bash
fly ssh console --app operious-ai-imad \
  --command "sh -lc 'cd /app && ALEMBIC_DATABASE_URL=\$ALEMBIC_DATABASE_URL alembic current'"
```

Expected: current production revision is printed, normally `0039_dlq_replay_cols (head)`.

```bash
fly ssh console --app operious-ai-imad \
  --command "sh -lc 'cd /app && ALEMBIC_DATABASE_URL=\$ALEMBIC_DATABASE_URL alembic history --verbose | head -20'"
```

Expected: recent migration history shows the applied revision and its immediate parent.

```bash
timeout 25s fly logs --app operious-ai-imad | grep -E "sqlalchemy|asyncpg|alembic|migration|RLS|UndefinedColumn|ForeignKeyViolation"
```

Expected: the first repeated database error identifies whether rollback is even safe.

## Impact Scope
| Migration Type | Rollback Safety | Broken | Affected Users |
| --- | --- | --- | --- |
| Add nullable column or index | Usually safe to downgrade one step. | Queries or performance may regress until restored. | Routes using the changed table. |
| Add table with no production writes yet | Safe if table is empty. | Features depending on the table fail. | Tenants using the new feature. |
| Add NOT NULL, drop column, alter FK | Unsafe without data analysis. | Old and new code may disagree on schema. | Potentially all tenants. |
| RLS policy or role change | High severity; rollback or fix-forward depends on exposure. | Tenant isolation may be affected. | All tenants if `operious_app` isolation is impacted. |

## Recovery Steps
1. Read every step before executing any downgrade.

   Command:

   ```bash
   fly ssh console --app operious-ai-imad \
     --command "sh -lc 'cd /app && ALEMBIC_DATABASE_URL=\$ALEMBIC_DATABASE_URL alembic current'"
   ```

   Expected: prints the exact current revision. Write it into the incident notes.

   If it does not work: use Neon SQL Editor as `neondb_owner` and run `SELECT version_num FROM alembic_version;`.

2. Identify the applied migration and parent.

   Command:

   ```bash
   fly ssh console --app operious-ai-imad \
     --command "sh -lc 'cd /app && ALEMBIC_DATABASE_URL=\$ALEMBIC_DATABASE_URL alembic history --verbose | head -20'"
   ```

   Expected: the current revision appears above the previous revision. Confirm whether the downgrade body is safe before running it.

   If it does not work: inspect `apps/backend/migrations/versions` on branch `phase-2-2-stabilized` and use Neon `alembic_version` output to identify the file.

3. Decide whether rollback is safe.

   Command:

   ```bash
   git show --stat --oneline HEAD -- apps/backend/migrations/versions
   ```

   Expected: you can see the migration file that introduced the schema change.

   If it does not work: do not downgrade based on memory. Open the migration file and read both `upgrade()` and `downgrade()`.

4. Roll back exactly one migration if it is safe.

   Command:

   ```bash
   fly ssh console --app operious-ai-imad \
     --command "sh -lc 'cd /app && ALEMBIC_DATABASE_URL=\$ALEMBIC_DATABASE_URL alembic downgrade -1'"
   ```

   Expected: Alembic completes one downgrade. It should not skip revisions.

   If it does not work: stop. Do not run `downgrade -2` or edit `alembic_version` manually. Inspect the failed downgrade SQL and decide whether fix-forward is safer.

5. Verify current head immediately after the downgrade.

   Command:

   ```bash
   fly ssh console --app operious-ai-imad \
     --command "sh -lc 'cd /app && ALEMBIC_DATABASE_URL=\$ALEMBIC_DATABASE_URL alembic current'"
   ```

   Expected: current revision is now the immediate parent of the failed migration.

   If it does not work: stop application changes and inspect Neon directly. Do not perform another downgrade until the current state is known.

6. Redeploy the application version that matches the downgraded schema.

   Command:

   ```bash
   fly deploy --image "registry.fly.io/operious-ai-imad:${FLY_ROLLBACK_VERSION:?set FLY_ROLLBACK_VERSION to the app image compatible with the downgraded schema}" \
     --app operious-ai-imad
   ```

   Expected: Fly deploys the schema-compatible app image.

   If it does not work: fix forward with a migration that restores compatibility. Do not leave old code running against an unknown schema.

7. For unsafe rollback scenarios, fix forward instead.

   Command:

   ```bash
   timeout 120s fly logs --app operious-ai-imad | grep -E "sqlalchemy|asyncpg|alembic|UndefinedColumn|NotNullViolation|ForeignKeyViolation"
   ```

   Expected: the first database error points to the required fix-forward migration or code adjustment.

   If it does not work: use Sentry event details and Neon query history to identify the failing statement.

## Verification
```bash
fly ssh console --app operious-ai-imad \
  --command "sh -lc 'cd /app && ALEMBIC_DATABASE_URL=\$ALEMBIC_DATABASE_URL alembic current'"
```

Expected: revision is the intended post-rollback revision and not an unknown intermediate state.

```bash
curl -sS https://operious-ai-imad.fly.dev/api/v1/health | python3 -m json.tool | grep '"status"'
```

Expected output includes:

```text
"status": "ok"
```

```bash
curl -sS https://operious-ai-imad.fly.dev/api/v1/session/sessions \
  -H "X-Tenant-ID: anker-pilot" \
  -H "Authorization: Bearer ${OPERIOUS_OPERATOR_TOKEN:?set OPERIOUS_OPERATOR_TOKEN to an Auth0 operator token from https://app.operious.com}" | \
  python3 -m json.tool | grep '"total"'
```

Expected: tenant-scoped session reads work and return non-zero `total`.

## Post-Incident Actions
- Document the failed migration revision, downgrade command output, resulting Alembic head, affected tables, and whether data was written in the failed schema.
- Write a corrected migration and test locally against the standard Wedge 4 database before redeploying.
- Update the migration pre-flight checklist for NOT NULL constraints, dropped columns, FK changes, RLS changes, and backward compatibility with the previous Fly image.
- If tenant isolation was involved, also complete `docs/runbooks/tenant-isolation-incident.md` and include RLS-enforced proof queries.
