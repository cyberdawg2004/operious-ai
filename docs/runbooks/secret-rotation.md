# Secret Rotation Runbook

Production anchors: Fly app `operious-ai-imad`, backend URL https://operious-ai-imad.fly.dev, Command Center https://app.operious.com, Neon Postgres roles `operious_app` and `neondb_owner`, Auth0 application `operious-dev`, Upstash Redis, Sentry, Anthropic, tenant `anker-pilot`, and Alembic head `0039_dlq_replay_cols`.

## When to Rotate
- Suspected credential compromise
- Team member departure with production access
- Quarterly scheduled rotation (recommended)
- After any security incident regardless of scope

## Pre-Rotation Checklist
1. Verify current system health before starting:

   ```bash
   curl https://operious-ai-imad.fly.dev/api/v1/health
   ```

   Expected: `status=ok`.

2. Confirm you have access to Neon console, Auth0 dashboard, Anthropic console, Upstash console, and Fly.io.
3. Do not rotate more than one secret at a time.
4. Record the rotation in the incident log with timestamp, operator, secret name, Fly release created, and verification result.

## Secrets Inventory

### DATABASE_URL
- Fly secret name: `DATABASE_URL`
- What uses it: FastAPI app DB connection through the Neon `operious_app` role. This is the application role used for tenant-scoped reads and writes under RLS.
- How to generate a new value: Neon console -> Settings -> Roles -> `operious_app` -> Reset password. Copy the new pooled or direct Postgres URL and preserve the `postgresql+asyncpg://` scheme expected by the backend.
- Rotation command:

  ```bash
  read -rsp "New DATABASE_URL: " NEW_DATABASE_URL; echo
  fly secrets set DATABASE_URL="$NEW_DATABASE_URL" --app operious-ai-imad
  unset NEW_DATABASE_URL
  ```

- Verification command:

  ```bash
  curl https://operious-ai-imad.fly.dev/api/v1/health
  curl https://operious-ai-imad.fly.dev/api/v1/session/sessions \
    -H "X-Tenant-ID: anker-pilot" | python3 -m json.tool | grep '"total"'
  ```

  Expected: health returns `status=ok`, and the session query returns a non-zero `total`.

- Zero-downtime: YES. Fly restarts machines with the new secret.
- Rollback: run `fly secrets set DATABASE_URL="$PREVIOUS_DATABASE_URL" --app operious-ai-imad` with the previous Neon URL from the incident log or password vault, then repeat the verification commands.
- Note: must also update local `.env` if used for local development.

### ALEMBIC_DATABASE_URL
- Fly secret name: `ALEMBIC_DATABASE_URL`
- What uses it: Alembic migrations through the Neon `neondb_owner` role. It is not used for normal application request handling.
- How to generate a new value: Neon console -> Settings -> Roles -> `neondb_owner` -> Reset password. Copy the new owner URL and preserve the `postgresql+asyncpg://` scheme expected by the backend.
- Rotation command:

  ```bash
  read -rsp "New ALEMBIC_DATABASE_URL: " NEW_ALEMBIC_DATABASE_URL; echo
  fly secrets set ALEMBIC_DATABASE_URL="$NEW_ALEMBIC_DATABASE_URL" --app operious-ai-imad
  unset NEW_ALEMBIC_DATABASE_URL
  ```

- Verification command:

  ```bash
  fly ssh console --app operious-ai-imad \
    --command "sh -lc 'cd /app && ALEMBIC_DATABASE_URL=\$ALEMBIC_DATABASE_URL alembic current'"
  ```

  Expected: Alembic prints `0039_dlq_replay_cols (head)` or the current production head without error.

- Zero-downtime: YES. Rotating this does not affect running application traffic; it only affects migration commands.
- Rollback: run `fly secrets set ALEMBIC_DATABASE_URL="$PREVIOUS_ALEMBIC_DATABASE_URL" --app operious-ai-imad`, then rerun `alembic current`.

### ANTHROPIC_API_KEY
- Fly secret name: `ANTHROPIC_API_KEY`
- What uses it: Diagnostic Agent LLM calls through the Anthropic provider path.
- How to generate a new value: https://console.anthropic.com -> API Keys -> Create key. Keep the old key active until the new key is verified.
- Rotation command:

  ```bash
  read -rsp "New ANTHROPIC_API_KEY: " NEW_ANTHROPIC_API_KEY; echo
  fly secrets set ANTHROPIC_API_KEY="$NEW_ANTHROPIC_API_KEY" --app operious-ai-imad
  unset NEW_ANTHROPIC_API_KEY
  ```

- Verification command:

  ```bash
  curl https://operious-ai-imad.fly.dev/api/v1/health
  ```

  Then monitor Sentry for 5 minutes after rotation. No new `CognitionLLMConfigurationError` events means the new key is accepted by the runtime.

- Zero-downtime: YES. New tasks use the new key after Fly restarts the affected machines.
- Rollback: run `fly secrets set ANTHROPIC_API_KEY="$PREVIOUS_ANTHROPIC_API_KEY" --app operious-ai-imad`, verify health, and revoke the failed key in Anthropic console.
- Note: revoke the old key in Anthropic console only after confirming the new key works.

### AUTH0_CLIENT_SECRET
- Fly secret name: `AUTH0_CLIENT_SECRET`
- What uses it: Auth0 machine-to-machine authentication for the Operious Auth0 application.
- How to generate a new value: Auth0 dashboard -> Applications -> `operious-dev` -> Settings -> Rotate Secret. Keep the previous value available until login and token flows are verified.
- Rotation command:

  ```bash
  read -rsp "New AUTH0_CLIENT_SECRET: " NEW_AUTH0_CLIENT_SECRET; echo
  fly secrets set AUTH0_CLIENT_SECRET="$NEW_AUTH0_CLIENT_SECRET" --app operious-ai-imad
  unset NEW_AUTH0_CLIENT_SECRET
  ```

- Verification command:

  ```bash
  curl https://operious-ai-imad.fly.dev/api/v1/health
  ```

  Then open https://app.operious.com and log in with Auth0. The Auth0 session must succeed and reach the Command Center.

- Zero-downtime: YES.
- Rollback: run `fly secrets set AUTH0_CLIENT_SECRET="$PREVIOUS_AUTH0_CLIENT_SECRET" --app operious-ai-imad`, then verify login through https://app.operious.com again.

### UPSTASH_REDIS_URL
- Fly secret name: `UPSTASH_REDIS_URL`
- What uses it: Upstash Redis connection string when the deployment uses the Upstash-named secret. Redis backs Celery broker behavior, queue depth checks, webhook nonce ledger, admission gate checks, and quota runtime coordination.
- How to generate a new value: Upstash console -> Database -> Details -> Reset password. Reset only the password; do not flush the Redis database.
- Rotation command:

  ```bash
  read -rsp "New UPSTASH_REDIS_URL: " NEW_UPSTASH_REDIS_URL; echo
  fly secrets set UPSTASH_REDIS_URL="$NEW_UPSTASH_REDIS_URL" --app operious-ai-imad
  unset NEW_UPSTASH_REDIS_URL
  ```

- Verification command:

  ```bash
  curl https://operious-ai-imad.fly.dev/api/v1/health | python3 -m json.tool | grep '"status"'
  ```

  Expected: health returns `status=ok`; queue statuses should be `ok` or `unknown`, not `error`.

- Zero-downtime: YES. Celery workers reconnect automatically after Fly restarts machines with the new secret.
- Rollback: run `fly secrets set UPSTASH_REDIS_URL="$PREVIOUS_UPSTASH_REDIS_URL" --app operious-ai-imad`, then verify health and queue status.
- Note: existing queued tasks may be lost if Redis is flushed. Only reset the password.

### REDIS_URL
- Fly secret name: `REDIS_URL`
- What uses it: Redis connection string when the deployment uses the generic Redis secret. It has the same operational surface as `UPSTASH_REDIS_URL`: Celery broker behavior, queue depth checks, webhook nonce ledger, admission gate checks, and quota runtime coordination.
- How to generate a new value: Upstash console -> Database -> Details -> Reset password. Copy the Redis URL using the current production TLS mode.
- Rotation command:

  ```bash
  read -rsp "New REDIS_URL: " NEW_REDIS_URL; echo
  fly secrets set REDIS_URL="$NEW_REDIS_URL" --app operious-ai-imad
  unset NEW_REDIS_URL
  ```

- Verification command:

  ```bash
  curl https://operious-ai-imad.fly.dev/api/v1/health | python3 -m json.tool | grep '"status"'
  ```

  Expected: health returns `status=ok`; queue statuses should be `ok` or `unknown`, not `error`.

- Zero-downtime: YES. Celery workers reconnect automatically after Fly restarts machines with the new secret.
- Rollback: run `fly secrets set REDIS_URL="$PREVIOUS_REDIS_URL" --app operious-ai-imad`, then verify health and queue status.
- Note: if both `REDIS_URL` and `UPSTASH_REDIS_URL` are configured, rotate the one currently used by production settings first and leave the other unchanged until after verification.

### SENTRY_DSN
- Fly secret name: `SENTRY_DSN`
- What uses it: Error reporting, tracing, and alerting for the FastAPI backend and workers.
- How to generate a new value: Sentry -> Project Settings -> Client Keys -> Add DSN. Keep the old DSN active until the new DSN receives a test event.
- Rotation command:

  ```bash
  read -rsp "New SENTRY_DSN: " NEW_SENTRY_DSN; echo
  fly secrets set SENTRY_DSN="$NEW_SENTRY_DSN" --app operious-ai-imad
  unset NEW_SENTRY_DSN
  ```

- Verification command:

  ```bash
  curl https://operious-ai-imad.fly.dev/api/v1/health
  ```

  Trigger a controlled test error through the approved operator path and confirm it appears in the Operious Sentry project.

- Zero-downtime: YES.
- Rollback: run `fly secrets set SENTRY_DSN="$PREVIOUS_SENTRY_DSN" --app operious-ai-imad`, then verify that Sentry receives a new event from production.

### AUDIT_EXPORT_HMAC_SECRET
- Fly secret name: `AUDIT_EXPORT_HMAC_SECRET`
- What uses it: HMAC-SHA256 signing of tenant-scoped audit exports from `/api/v1/audit/export` and verification through `/api/v1/audit/verify`.
- How to generate a new value:

  ```bash
  openssl rand -hex 32
  ```

- Rotation command:

  ```bash
  fly secrets set AUDIT_EXPORT_HMAC_SECRET="$(openssl rand -hex 32)" --app operious-ai-imad
  ```

- Verification command:

  ```bash
  curl https://operious-ai-imad.fly.dev/api/v1/audit/export \
    -H "X-Tenant-ID: anker-pilot" | \
    python3 -m json.tool | grep '"algorithm"'
  ```

  Expected: response includes `HMAC-SHA256`.

- Zero-downtime: YES.
- Rollback: run `fly secrets set AUDIT_EXPORT_HMAC_SECRET="$PREVIOUS_AUDIT_EXPORT_HMAC_SECRET" --app operious-ai-imad` if verification fails and old exports must remain verifiable with the previous key.
- IMPORTANT: after rotation, previously exported audit files will fail verification with the new key. Archive old exports before rotating. The `key_hint` in old exports will differ from the new `key_hint`.

## Post-Rotation Verification

After any rotation, run the full health check sequence:

1. Health:

   ```bash
   curl https://operious-ai-imad.fly.dev/api/v1/health
   ```

2. Tenant-scoped sessions:

   ```bash
   curl https://operious-ai-imad.fly.dev/api/v1/session/sessions \
     -H "X-Tenant-ID: anker-pilot" | python3 -m json.tool | grep '"total"'
   ```

   Expected: `total` is non-zero.

3. Monitor Sentry for 10 minutes for unexpected errors.
4. Verify queue depths are normal via Command Center Queue Status at https://app.operious.com.
5. If any check fails: revert the rotated secret immediately with the rollback command for that secret, then record the failure in the incident log.
