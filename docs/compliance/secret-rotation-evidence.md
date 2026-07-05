# Secret Rotation Evidence

**Date:** 2026-07-05  
**Environment:** `operious-ai-imad` (Fly.io, region `iad`)  
**Git commit:** `6c34e02` (branch `phase-2-2-stabilized`)

## Deployed Secrets Inventory

All secrets are stored in Fly.io secrets (encrypted at rest by Fly).  
No secret values are committed to the repository. `git log --all -- '*.env' '**/.env'` returns empty.

| Secret | Category | Rotation Runbook | Last Confirmed Present |
|--------|----------|-----------------|----------------------|
| `ANTHROPIC_API_KEY` | LLM provider | Rotate in Anthropic console → `fly secrets set` | 2026-07-05 |
| `AUDIT_EXPORT_HMAC_SECRET` | Audit integrity | Generate new 256-bit random hex → `fly secrets set` | 2026-07-05 |
| `DATABASE_URL` | Postgres connection | Neon console → rotate password → `fly secrets set` | 2026-07-05 |
| `ALEMBIC_DATABASE_URL` | Migration connection | Same as DATABASE_URL | 2026-07-05 |
| `TENANT_CREDENTIAL_MASTER_KEY` | Tenant credential DEK wrapping | Generate new AES-256 key → run `scripts/reencrypt_tenant_credentials.py` → `fly secrets set` | 2026-07-05 |
| `DATA_PROTECTION_MASTER_KEYS` | Customer data envelope encryption | Add new version to JSONB array → set `DATA_PROTECTION_ACTIVE_MASTER_KEY_VERSION` → `fly secrets set` | 2026-07-05 |
| `DATA_PROTECTION_ACTIVE_MASTER_KEY_VERSION` | Active DEK version pointer | Updated alongside `DATA_PROTECTION_MASTER_KEYS` | 2026-07-05 |
| `OPERIOUS_KMS_SA_JSON` | GCP KMS service account | Rotate GCP service account key → `fly secrets set` | 2026-07-05 |
| `OPERIOUS_KMS_KEY_RESOURCE` | GCP KMS key path | Updated when GCP key rotated | 2026-07-05 |
| `GOOGLE_APPLICATION_CREDENTIALS` | GCP auth | Rotated with service account | 2026-07-05 |
| `SECRET_KEY` | FastAPI session signing | Generate new 256-bit random hex → `fly secrets set` | 2026-07-05 |
| `VOICE_SESSION_TOKEN_SECRET` | Voice WebSocket HMAC | Generate new 256-bit random hex → `fly secrets set` | 2026-07-05 |
| `LIVE_SES_ACCESS_KEY_ID` / `LIVE_SES_SECRET_ACCESS_KEY` | AWS SES email delivery | Rotate IAM access key → `fly secrets set` | 2026-07-05 |
| `ATTACHMENTS_S3_ACCESS_KEY_ID` / `ATTACHMENTS_S3_SECRET_ACCESS_KEY` | AWS S3 attachments | Rotate IAM access key → `fly secrets set` | 2026-07-05 |
| `OPENAI_API_KEY` | OpenAI embeddings | Rotate in OpenAI console → `fly secrets set` | 2026-07-05 |
| `REDIS_URL` | Upstash Redis broker | Rotate in Upstash console → `fly secrets set` | 2026-07-05 |
| `CELERY_BROKER_URL` | RabbitMQ broker | Rotate in CloudAMQP → `fly secrets set` | 2026-07-05 |
| `RABBITMQ_MANAGEMENT_*` | RabbitMQ management API | Rotate in CloudAMQP → `fly secrets set` | 2026-07-05 |
| `AUTH0_*` | Auth0 configuration | Rotate in Auth0 dashboard (audience/domain/issuer/JWKS are not secrets — they're public endpoints) | 2026-07-05 |
| `SENTRY_DSN` | Error tracking | Rotate in Sentry settings → `fly secrets set` | 2026-07-05 |

## Rotation Procedure

1. **Generate new value**: use `openssl rand -hex 32` for HMAC/signing secrets; use provider console for API keys.
2. **Set in Fly**: `fly secrets set SECRET_NAME="<new_value>" --app operious-ai-imad`
3. **Verify deployment**: Fly triggers rolling restart; confirm `production readiness: READY` via `fly ssh console`.
4. **Update this document** with rotation date.

For tenant credential master key rotation, also run:
```bash
fly ssh console --app operious-ai-imad --command "bash -c 'cd /app && PYTHONPATH=/app python3 scripts/reencrypt_tenant_credentials.py --dry-run'"
```
Then without `--dry-run` to apply.

See `docs/runbooks/secret-rotation.md` for full runbook.

## Rotation Schedule

| Category | Rotation Frequency | Trigger |
|----------|-------------------|---------|
| API keys (LLM, AWS, OpenAI) | Every 90 days or on personnel change | Quarterly or incident |
| HMAC/signing secrets | Every 180 days or on suspected compromise | Semi-annual or incident |
| DB passwords | Every 90 days or on personnel change | Quarterly or incident |
| KMS service account | Every 180 days | Semi-annual |
| Tenant credential master key | Annually or on suspected compromise | Annual or incident |

## Evidence of No Committed Secrets

```bash
# Run from repo root — should return empty
git log --all --full-history -- '**/.env' '*.env' '.env*'
git grep -r "ANTHROPIC_API_KEY\s*=\s*[a-z]" -- '*.py' '*.env' '*.toml' '*.yml'
```

Both return empty. All secrets are injected via `fly secrets set` and available as environment variables at runtime only.
