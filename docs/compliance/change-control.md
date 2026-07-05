# Operious AI — Change-Control Process

**Version:** 2026-07-05

---

## 1. Overview

Operious AI operates three distinct change-control tracks, each with different gate requirements:

| Track | What changes | Gate |
|---|---|---|
| **Tenant configuration** | Per-tenant policy, knowledge, topology, connectors, governance rules | Dual-control propose → approve in the config-change ledger |
| **Code and infrastructure** | Application code, migrations, Fly.io secrets, dependencies | Branch → PR → CI → Fly deploy |
| **Crisis / emergency** | Overrides that bypass normal governance flow | `crisis` endpoint; explicit crisis policy; audit-logged |

---

## 2. Tenant Configuration Changes

### 2.1 The Config-Change Ledger

All production tenant configuration mutations flow through a durable change-request ledger (`tenant_config_change_requests` table). This is enforced in production by `TENANT_CONFIG_ALLOW_SELF_APPROVAL=None` (effective value: `false` in production, per `config.py` `tenant_config_self_approval_allowed` property).

The lifecycle is:

```
PROPOSED ──► APPROVED ──► APPLIED
     │                        │
     └──────► REJECTED         └──► (config takes effect)
     │
     └──────► REVOKED
```

**Operational events** appended to the chronology for each transition (source: `OperationalAct` enum in `app/governance/capability/acts.py`):
- `governance:tenant_config_change_propose`
- `governance:tenant_config_change_approve`
- `governance:tenant_config_change_reject`
- `governance:tenant_config_change_apply`
- `governance:tenant_config_change_revoke`

### 2.2 Required Capabilities per Step

| Step | Required Capability | Auth0 Role(s) |
|---|---|---|
| Propose a change | Domain capability (e.g. `tenant.knowledge.write`, `tenant.policy.write`, `tenant.channel.admin`, etc.) | Corresponding domain writer role |
| Approve/apply a change | `tenant.config.approve` | `TenantApprover` |
| Approve a connector change | `tenant.connector.approve` | `TenantConnectorApprover` |

**Separation of duties is enforced in code.** `require_config_apply_authorization` raises `HTTP 403 independent_approval_required` if the caller attempts to approve their own proposal. In production, `TENANT_CONFIG_ALLOW_SELF_APPROVAL` is always `false` regardless of flag value.

### 2.3 Safety-Relevant Policy Types

Policy changes of types `action_tools_policy`, `resolution_autonomy_policy`, `resolution_taxonomy_policy`, and `warranty_refund_rules` are validated by `TenantConfigChangeRequestService` at proposal time. Invalid policy parameters are rejected before the proposal is persisted. Source: `app/services/tenant_config_change_request_service.py`.

### 2.4 Connector Config Lifecycle

Connector configuration changes follow a parallel dual-control pattern using `OperationalAct.CONNECTOR_CONFIG_PROPOSE` and `CONNECTOR_CONFIG_APPROVE`. This ensures that credentials for outbound connectors (e.g., Shopify, Jira, custom webhooks) are reviewed by a second principal before being activated.

---

## 3. Code Changes

### 3.1 Normal Path

1. **Branch:** Work is done on a feature branch (current: `phase-2-2-stabilized`).
2. **PR:** Pull request opened against `main` (or the active stabilization branch). Code review required.
3. **CI:** Automated checks run:
   - `pyright` — type checking
   - `ruff` — linting
   - `pytest` — test suite (run from repo root, not `apps/backend`)
4. **Deploy:** `fly deploy --app operious-ai-imad`
   - Fly runs `alembic upgrade head` as the release command before any machines are replaced (defined in `fly.toml` `[deploy] release_command`). A failed migration aborts the deploy; no machines are updated.
   - Health check: `GET /api/v1/live` (30 s interval, 5 s timeout, 20 s grace period).

### 3.2 Migration Safety Rules

- All migrations run `ENABLE ROW LEVEL SECURITY` + `FORCE ROW LEVEL SECURITY` + `CREATE POLICY tenant_isolation` for every new tenant-scoped table.
- `NOT NULL` constraints, column drops, and FK changes require migration pre-flight review.
- Migrations are write-once; the `alembic upgrade head` release command prevents partial deployment of a schema that newer code has not yet committed to.

### 3.3 Rollback

See `docs/runbooks/fly-deploy-rollback.md` (application) and `docs/runbooks/neon-migration-rollback.md` (schema). Application rollback does not roll back migrations; both must be considered together.

---

## 4. Emergency / Crisis Changes

### 4.1 Crisis Governance Endpoint

A `crisis` governance endpoint exists for deploying emergency governance overrides that bypass the normal tenant-config change-request flow. This endpoint is recorded in the `governance_decisions` table via `governance:crisis_deploy` (`OperationalAct.GOVERNANCE_CRISIS_DEPLOY`).

**Use conditions:** The crisis path is intended only for active incidents where the normal approval cycle cannot complete in time to stop harm (e.g., a rogue AI action pattern that must be stopped immediately).

**Controls:**
- Requires `platform.tenant.admin` capability.
- Every crisis deployment is appended to the governance chronology.
- Crisis policy changes are time-boxed and must be followed by a normal change-request to make the change durable.

### 4.2 Secret Rotation (Emergency)

Emergency secret rotation (e.g., compromised webhook HMAC key, compromised Fly secret) follows `docs/runbooks/secret-rotation.md`. Secrets are updated via `fly secrets set --app operious-ai-imad <KEY>=<VALUE>`, which triggers a rolling restart of affected machines.

---

## 5. Audit Trail

| Audit record | Storage | Retention |
|---|---|---|
| Tenant config change-requests | `tenant_config_change_requests` table (Neon) | Indefinite (retained for compliance) |
| Governance decisions | `governance_decisions` table (Neon) | Indefinite |
| Operational event chronology | Tenant-scoped event tables (Neon) | Tenant retention period |
| Fly deploy history | Fly release history | Fly platform policy |

Audit exports are signed with HMAC-SHA256 (`AUDIT_EXPORT_HMAC_SECRET` via `fly secrets set`) and require the `tenant.audit.export` capability to access.

---

## 6. Change Freeze Windows

No formal change freeze windows are defined at this stage. High-risk changes (NOT NULL constraints, RLS policy modifications, connector credential changes) require senior review and should not be deployed without a tested rollback plan.

---

## Contact

Change-control questions: `ops@operious.com`  
Security-relevant change reviews: `security@operious.com`
