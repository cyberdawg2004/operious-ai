# Fly.io Deployment Rollback

## Overview
Use this runbook when a Fly.io deploy of `operious-ai-imad` causes a confirmed regression in the production backend at https://operious-ai-imad.fly.dev. Rollback can restore service quickly, but it does not roll back Neon Postgres migrations, so application rollback is only safe when the previous application version is compatible with the current schema head `0039_dlq_replay_cols`. Production anchors are Singapore Fly app `operious-ai-imad`, Command Center at https://app.operious.com, marketing at https://www.operious.com, Neon Postgres roles `operious_app` with `BYPASSRLS=False` and `neondb_owner`, Upstash Redis via `REDIS_URL` or `UPSTASH_REDIS_URL`, Auth0 domain `operious-dev.uk.auth0.com`, Sentry, and branch `phase-2-2-stabilized`.

## Trigger Conditions
- Immediately after `fly deploy`, `GET /api/v1/health` returns non-200 or `status` is `critical`.
- `GET /api/v1/session/sessions` for `anker-pilot` returns incorrect data, zero sessions unexpectedly, or tenant-scope errors.
- Sentry error rate spikes after a Fly release.
- Command Center at https://app.operious.com shows broken Queue Status, DLQ Inspector, or session data after deploy.
- Functional regression is confirmed and cannot be fixed forward safely within 15 minutes.

## Immediate Assessment (< 5 minutes)
```bash
curl -sS -i https://operious-ai-imad.fly.dev/api/v1/health | head -20
```

Expected: HTTP 200 and a health JSON body. If non-200, rollback is likely appropriate unless this is a simple secret/config issue.

```bash
curl -sS https://operious-ai-imad.fly.dev/api/v1/session/sessions \
  -H "X-Tenant-ID: anker-pilot" \
  -H "Authorization: Bearer ${OPERIOUS_OPERATOR_TOKEN:?set OPERIOUS_OPERATOR_TOKEN to an Auth0 operator token from https://app.operious.com}" | \
  python3 -m json.tool | grep '"total"'
```

Expected: sessions return a non-zero `total` for `anker-pilot`. If this returns 401 or 403, confirm Auth0 operator token before blaming the deploy.

```bash
fly status --app operious-ai-imad
```

Expected: web and worker process groups are running. If machines are unhealthy after deploy, inspect the release list and prepare rollback.

```bash
fly releases --app operious-ai-imad | head -5
```

Expected: the current release and previous releases are visible. Note the last known good version.

## Impact Scope
| Condition | Broken | Still Works | Affected Users |
| --- | --- | --- | --- |
| Bad application code deploy | Backend routes or workers may fail. | Neon data remains intact; previous image may still be deployable. | All tenants using affected routes or queues. |
| Bad secret/config deploy | Specific provider, Auth0, Redis, or DB access may fail. | Code may be healthy after secret correction. | Tenants whose flow touches the bad config. |
| Migration incompatibility | Old image may not run against current schema. | Fix-forward remains available. | All production tenants if app cannot boot. |

## Recovery Steps
1. Decide rollback versus fix-forward.

   Command:

   ```bash
   curl -sS -i https://operious-ai-imad.fly.dev/api/v1/health | head -20
   ```

   Expected: if the issue is application code and a safe fix takes more than 15 minutes, rollback. If it is a secret or configuration issue that can be corrected in under 5 minutes, fix forward.

   If it does not work: if health hangs or returns 5xx, prioritize rollback unless the deploy also included a migration the old code cannot tolerate.

2. Identify the previous good deployment.

   Command:

   ```bash
   fly releases --app operious-ai-imad | head -5
   ```

   Expected: note the version number of the last known good deployment, such as `v123`.

   If it does not work: use the Fly dashboard release history for `operious-ai-imad`.

3. Verify migration compatibility before rollback.

   Command:

   ```bash
   fly ssh console --app operious-ai-imad \
     --command "sh -lc 'cd /app && ALEMBIC_DATABASE_URL=\$ALEMBIC_DATABASE_URL alembic current'"
   ```

   Expected: production Alembic head is `0039_dlq_replay_cols (head)`.

   If it does not work: do not roll back blindly. If the current code cannot start far enough to run Alembic, use Neon SQL Editor as `neondb_owner` to inspect `alembic_version`.

4. Roll back to the previous application image.

   Command:

   ```bash
   fly deploy --image "registry.fly.io/operious-ai-imad:${FLY_ROLLBACK_VERSION:?set FLY_ROLLBACK_VERSION to the previous good Fly release version}" \
     --app operious-ai-imad
   ```

   Expected: Fly deploys the previous image and starts replacement machines.

   If it does not work: if the registry tag is not available, use the exact image reference shown in Fly release history. If the old image fails because of schema changes, stop rollback and fix forward.

5. Verify health after rollback.

   Command:

   ```bash
   curl https://operious-ai-imad.fly.dev/api/v1/health
   ```

   Expected: HTTP 200 with `status` returning to `ok`.

   If it does not work: inspect `fly logs --app operious-ai-imad` and confirm the old image is compatible with the current Neon schema.

6. Verify tenant-scoped sessions after rollback.

   Command:

   ```bash
   curl https://operious-ai-imad.fly.dev/api/v1/session/sessions \
     -H "X-Tenant-ID: anker-pilot" \
     -H "Authorization: Bearer ${OPERIOUS_OPERATOR_TOKEN:?set OPERIOUS_OPERATOR_TOKEN to an Auth0 operator token from https://app.operious.com}" | python3 -m json.tool | \
     grep '"total"'
   ```

   Expected: sessions return non-zero `total` for `anker-pilot`.

   If it does not work: if tenant-scoped reads fail after rollback, suspect schema incompatibility or Auth0 token scope. Do not roll back database migrations from this runbook.

7. If rollback is unsafe because of migrations, fix forward only.

   Command:

   ```bash
   fly releases --app operious-ai-imad | head -5
   ```

   Expected: current bad release is identified so the fix-forward deploy can target the branch `phase-2-2-stabilized`.

   If it does not work: use Sentry and Fly logs to identify the smallest safe code or config correction.

## Verification
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
  -H "Authorization: Bearer ${OPERIOUS_OPERATOR_TOKEN:?set OPERIOUS_OPERATOR_TOKEN to an Auth0 operator token from https://app.operious.com}" | python3 -m json.tool | \
  grep '"total"'
```

Expected: `total` is non-zero.

```bash
fly status --app operious-ai-imad
```

Expected: `web`, `worker_diagnostic`, `worker_escalation`, `worker_supervisor`, `worker_sop`, and `worker_maintenance` are running.

## Post-Incident Actions
- Record the bad Fly release, rollback target, commit range, Sentry errors, and exact decision for rollback versus fix-forward.
- Check `git log` on branch `phase-2-2-stabilized` to identify the change that caused the regression.
- Write the fix on a new branch or the active stabilization branch and redeploy only after local checks match the risk level.
- Confirm no database migration rollback was performed as part of this Fly application rollback.
