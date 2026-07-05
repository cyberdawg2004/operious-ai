# Operious AI — Incident Response Plan

**Version:** 2026-07-05  
**Security contact:** `security@operious.com`  
**Operations contact:** `ops@operious.com`  
**Production endpoint:** `https://operious-ai-imad.fly.dev`  
**Command Center:** `https://app.operious.com`

---

## 1. Severity Levels

| Level | Definition | Examples | Response SLA |
|---|---|---|---|
| **P0 — Critical** | Active confirmed cross-tenant data exposure, or complete service unavailability affecting all tenants | `operious_app` has `BYPASSRLS=True`; confirmed tenant isolation breach; full backend down | Immediate; on-call escalation within 15 min |
| **P1 — High** | Significant security control failure or major functional regression affecting a tenant's live flows | Auth0 JWT verification bypassed; rate limiting disabled in production; DLQ spike above threshold; queue age SLO breach (`ALERT_QUEUE_AGE_CRITICAL_SECONDS=600`) | Response within 1 hour |
| **P2 — Medium** | Degraded service with a workaround available; security-relevant anomaly not yet confirmed as a breach | Redis memory pressure above 85% (`ALERT_REDIS_MEMORY_PCT=85.0`); DB pool utilization above 90% (`ALERT_DB_POOL_UTILIZATION=0.9`); provider circuit open; semantic circuit tripped | Response within 4 hours |
| **P3 — Low** | Non-critical issue; no security impact; no tenant data at risk | Single-worker restart; minor UI degradation in Command Center; replay mismatch on a single DLQ task | Response within 1 business day |

---

## 2. Detection

### 2.1 Sentry

All production errors are routed to Sentry (`SENTRY_DSN` set via `fly secrets set`). Sentry is initialized in `app/main.py` via `_init_sentry()` with `SENTRY_TRACES_SAMPLE_RATE=0.1`. `SENTRY_SEND_DEFAULT_PII=false`.

Sentry triggers include: unhandled exceptions, auth errors, database errors, RLS-related exceptions, and any `500` responses.

### 2.2 Structured Logs

All production processes emit JSON-structured logs (`LOG_JSON=true` effective in production). Logs include `request_id` (from `RequestContextMiddleware`), `tenant_id`, and structured event names. Logs are accessible via `fly logs --app operious-ai-imad`.

Key alert log events to watch:
- `untrusted_ingress_rejected` — spoofed authority headers blocked (S-01)
- `governance_invalidation_listener_failed` — governance pub/sub degraded
- `rate_limit_disabled` — rate limiting disabled (should never appear in production)
- `auth_disabled` — auth disabled (should never appear in production)
- `lifespan_shutdown_*` — unexpected worker restarts

### 2.3 AlertEvaluator (7 Conditions)

The `AlertEvaluator` (`app/hardening/observability/alert_evaluator.py`) evaluates the following conditions on each sweep:

| Condition | Threshold | Setting |
|---|---|---|
| `queue_age_slo_breach` | Queue age > 600 s | `ALERT_QUEUE_AGE_CRITICAL_SECONDS=600` |
| `dlq_spike` | DLQ depth delta ≥ 5 | `ALERT_DLQ_SPIKE_THRESHOLD=5` |
| `provider_circuit_open` | Any provider circuit in `OPEN` state | Hardcoded |
| `semantic_circuit_tripped` | Semantic circuit breaker tripped | `SEMANTIC_CIRCUIT_*` settings |
| `redis_memory_pressure` | Redis memory ≥ 85% | `ALERT_REDIS_MEMORY_PCT=85.0` |
| `db_pool_exhaustion` | DB pool utilization ≥ 90% | `ALERT_DB_POOL_UTILIZATION=0.9` |
| `replay_mismatch` | DLQ replay cannot find execution record | Hardcoded |

### 2.4 Health Endpoint

`GET /api/v1/live` — liveness probe (30 s interval, 5 s timeout, 20 s grace period per `fly.toml`).  
`GET /api/v1/health` — full readiness check including database, Redis, and worker state.

---

## 3. Response Procedures

### 3.1 Cross-Tenant Data Exposure (P0)

**Full runbook:** `docs/runbooks/tenant-isolation-incident.md`

**Immediate steps (< 5 min):**
1. Do not modify any data. Preserve screenshots, URLs, tenant IDs, record IDs, Auth0 user, and timestamp.
2. Verify `operious_app` role: `fly ssh console --app operious-ai-imad` → check `rolbypassrls=False`.
3. If `BYPASSRLS=True`: immediately `ALTER ROLE operious_app NOBYPASSRLS` as `neondb_owner` in Neon SQL Editor.
4. If RLS is missing on a table: `ALTER TABLE ... ENABLE ROW LEVEL SECURITY; ALTER TABLE ... FORCE ROW LEVEL SECURITY;` as `neondb_owner`.
5. Notify `security@operious.com` immediately.

**Escalation path:** Any confirmed cross-tenant exposure is a P0. Scale web to 0 (`fly scale count 0 --process-group web --app operious-ai-imad`) only if active confirmed exposure is ongoing and cannot be stopped otherwise.

### 3.2 Security Control Failure (P1)

Examples: auth verification bypassed, rate limiting off, CORS wildcard deployed, production readiness check failing.

1. Identify the failing control from Sentry or structured logs.
2. If the issue is a configuration change: correct via `fly secrets set` or `fly deploy` within 15 minutes.
3. If the issue requires a code fix: roll back per Section 3.4, then fix forward.
4. Notify `security@operious.com` within 1 hour.

### 3.3 Operational Degradation (P2/P3)

1. Check `fly status --app operious-ai-imad` for unhealthy machines.
2. Check `fly logs --app operious-ai-imad` for recurring errors.
3. Check Redis memory: `ALERT_REDIS_MEMORY_PCT=85.0` threshold.
4. Check DB pool: `ALERT_DB_POOL_UTILIZATION=0.9` threshold.
5. Follow the appropriate runbook:
   - Queue backlog: `docs/runbooks/queue-backlog.md`
   - DLQ replay: `docs/runbooks/dlq-replay.md`
   - Provider outage: `docs/runbooks/provider-outage.md`
   - Autoscaling: `docs/runbooks/autoscaling.md`

---

## 4. Rollback Procedures

### 4.1 Application Rollback

**Full runbook:** `docs/runbooks/fly-deploy-rollback.md`

```bash
# Identify previous good release
fly releases --app operious-ai-imad | head -5

# Roll back to previous image
fly deploy --image "registry.fly.io/operious-ai-imad:${FLY_ROLLBACK_VERSION}" \
  --app operious-ai-imad

# Verify health
curl -sS https://operious-ai-imad.fly.dev/api/v1/health
```

Trigger conditions: health returns non-200 after deploy, Sentry spike, confirmed regression not fixable in 15 min.

**Important:** Application rollback does NOT roll back Neon migrations. Only roll back when the previous image is compatible with the current schema.

### 4.2 Database Migration Rollback

**Full runbook:** `docs/runbooks/neon-migration-rollback.md`

```bash
# Check current migration state
fly ssh console --app operious-ai-imad \
  --command "sh -lc 'cd /app && ALEMBIC_DATABASE_URL=\$ALEMBIC_DATABASE_URL alembic current'"

# Downgrade exactly one step (only after reading both upgrade() and downgrade())
fly ssh console --app operious-ai-imad \
  --command "sh -lc 'cd /app && ALEMBIC_DATABASE_URL=\$ALEMBIC_DATABASE_URL alembic downgrade -1'"
```

This is the most dangerous operation in the platform. Read the full runbook before executing. RLS policy changes require special consideration.

### 4.3 Secret Rotation

**Runbook:** `docs/runbooks/secret-rotation.md`

---

## 5. Communication

| Situation | Audience | Channel |
|---|---|---|
| P0 confirmed breach | Internal team + affected tenants + `security@operious.com` | Direct communication; notify within 24 hours of confirmation |
| P1 security control failure | Internal team; `security@operious.com` | Within 1 hour of detection |
| P2/P3 operational | Internal team; `ops@operious.com` | Slack / internal channels |
| Subprocessor security incident | Internal team; `security@operious.com` | Track vendor notification; document in post-mortem |

External breach notification follows applicable law (GDPR 72-hour notification requirement where applicable).

---

## 6. Post-Mortem

| Severity | Timeline | Required |
|---|---|---|
| P0 | Within 2 business days | Yes — mandatory |
| P1 | Within 5 business days | Yes — mandatory |
| P2 | Within 10 business days | Recommended |
| P3 | Discretionary | Optional |

**Post-mortem minimum content:**
- Timeline of events (detection → containment → resolution)
- Root cause
- Impact scope (tenants affected, data at risk, duration)
- Remediation steps taken
- Preventive action items with owners and deadlines

For cross-tenant incidents: explicit statement of whether breach was confirmed or denied by RLS-enforced queries as `operious_app`. Per `docs/runbooks/tenant-isolation-incident.md`, the post-incident actions include: file a report even if suspected breach is disproven; if RLS was repaired manually, write a reviewed migration; audit recent deploys, migrations, and role changes.

---

## 7. Periodic Testing

- **Runbooks:** Review and update after any significant infrastructure change.
- **RLS verification:** Run `2026-07-05-rls-pass.json`-style proof queries before major releases.
- **Rollback drill:** Validate rollback path is exercisable before significant releases.
- **Alert thresholds:** Review `AlertEvaluator` condition thresholds quarterly.
