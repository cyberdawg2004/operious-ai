# Spec 1c-ext — Data-Protection Operational Admin API

- Date: 2026-06-02
- Status: Approved (design); pending implementation plan
- Phase: 1 (extension of spec 1c data protection)
- Closes: the operational-surface gap on GDPR DSAR erasure, legal hold, and
  retention-policy management (the crypto runtime exists but is unreachable).
- Credentials required: none
- Approach: A (single `tenant.privacy.admin` capability + mandatory audit trail)

## Purpose

Spec 1c built a real envelope-encryption runtime with crypto-shred DSAR erasure,
legal hold, retention purge, and key rotation. But those operations
(`erase_subject_key`, `create_legal_hold`, `set_retention_policy`) are **service
methods with no API endpoint and no task** — callable only from tests and the
crypto module. Consequences in production:

1. **DSAR (GDPR Article 17 right to erasure) cannot be fulfilled** through the
   running system — only via direct DB/script access.
2. **Legal hold cannot be set** to suspend erasure/retention for litigation.
3. **Retention is inert**: the daily purge task only acts on tenants with a
   `tenant_data_retention_policies` row, and there is no operational way to
   create one. Retention is policy-on-paper.

This spec exposes those operations through a capability-gated admin API so they
are actually usable, audited, and enterprise/SOC2/GDPR-defensible.

## Non-Goals

- Tenant-wide erasure (`erase_tenant_keys`) — catastrophic full-tenant crypto
  shred; a platform-offboarding operation, not tenant self-service. Not exposed.
- Master-key rotation API — an operational/ops-runbook concern, out of scope.
- Command-center UI — backend API only; UI is a later spec.
- Dual-control (propose/approve) on erasure — Approach B, not chosen. The audit
  trail plus legal-hold gate provide accountability without blocking the legal
  DSAR SLA.

## Current State

- `DataProtectionService` (`apps/backend/app/data_protection/crypto.py`) has:
  `create_legal_hold(tenant_id, scope, scope_id, reason, created_by) -> uuid.UUID`,
  `erase_subject_key(tenant_id, subject_id, requested_by) -> uuid.UUID`
  (raises `LegalHoldBlockedError` when blocked; writes a durable
  `DataProtectionErasureRequestRow` audit row in both blocked and completed
  cases), `set_retention_policy(tenant_id, retention_days, updated_by)`,
  `retention_days_for_tenant(tenant_id) -> int`, and `has_active_legal_hold(...)`.
- **Missing service methods:** `list_legal_holds`, `release_legal_hold`.
- `data_protection_legal_holds` columns: `hold_id, tenant_id, scope, scope_id,
  reason, created_by, created_at`. **No release columns.**
- `has_active_legal_hold` does not filter released holds (none exist yet).
- DI: `_data_protection_service(session)` in `dependencies/services.py` returns
  `DataProtectionService | None` (None only when no master key — impossible in
  production, which requires `TENANT_CREDENTIAL_MASTER_KEY`).
- Capabilities + dependency gates follow the `tenant.<domain>.<action>` pattern
  in `dependencies/authority.py`; Auth0 mappings in `auth/providers/jwt.py`.

## Component 1: `tenant.privacy.admin` capability

- Constant `TENANT_PRIVACY_ADMIN_CAPABILITY = "tenant.privacy.admin"` and a
  module-level dependency `require_tenant_privacy_admin(request)` in
  `dependencies/authority.py` (same pattern as `require_tenant_actions_approve`),
  added to `__all__` and the pinned `__all__` contract test.
- Auth0: `ROLE_CAPABILITY_MAP["TenantPrivacyAdmin"] = "tenant.privacy.admin"`;
  `PERMISSION_CAPABILITY_MAP["admin:tenant_privacy"] = "tenant.privacy.admin"`.
- **Not** added to the Operator role bundle — privacy/erasure is a distinct
  separation-of-duties role, the same stance taken for `tenant.actions.approve`.

## Component 2: Migration 0068 + service additions (legal-hold release)

### Migration 0068 (`0068_legal_hold_release`)

```sql
ALTER TABLE data_protection_legal_holds
  ADD COLUMN released_at TIMESTAMPTZ,
  ADD COLUMN released_by TEXT,
  ADD CONSTRAINT chk_released_by_when_released
    CHECK (released_at IS NULL OR released_by IS NOT NULL);
```

Reversible (drop constraint + 2 columns). FK/RLS posture unchanged.

### ORM + service

- `DataProtectionLegalHoldRow` gains `released_at: datetime | None`,
  `released_by: str | None`.
- `has_active_legal_hold` clauses gain `& (released_at IS NULL)` so a released
  hold no longer blocks erasure.
- New `list_legal_holds(tenant_id) -> tuple[LegalHoldRecord, ...]` — active
  (non-released) holds for the tenant, newest first. `LegalHoldRecord` is a
  frozen dataclass (`hold_id, scope, scope_id, reason, created_by, created_at`).
- New `release_legal_hold(hold_id, tenant_id, released_by) -> bool` — soft
  release (sets `released_at = now`, `released_by`); returns False if the hold
  is absent or belongs to another tenant (tenant-scoped, never cross-tenant).

## Component 3: DI dependency

`get_data_protection_service` in `dependencies/services.py`:
- Yields a `DataProtectionService` built from the request DB session.
- Raises `503 data_protection_not_configured` when `_data_protection_service`
  returns None (no master key — non-production only).

## Component 4: Router `data_protection.py` (`/api/v1/data-protection`)

All endpoints: `Depends(require_tenant_scope)` + `Depends(require_tenant_privacy_admin)`.
The acting principal (`requested_by`/`created_by`/`released_by`/`updated_by`) is
`_principal_or_400(authority)`.

| Method · Path | Service | Success | Errors |
|---|---|---|---|
| `POST /erasure-requests` `{subject_id}` | `erase_subject_key` | 200 `{request_id, status:"completed"}` | 409 `legal_hold_blocks_erasure` (LegalHoldBlockedError); 503 if unconfigured |
| `POST /legal-holds` `{scope, scope_id?, reason}` | `create_legal_hold` | 201 `{hold_id, scope, scope_id, reason}` | 400 `invalid_legal_hold_scope` (DataProtectionError); 503 |
| `GET /legal-holds` | `list_legal_holds` | 200 `{items:[...]}` | 503 |
| `DELETE /legal-holds/{hold_id}` | `release_legal_hold` | 204 | 404 `legal_hold_not_found`; 503 |
| `PUT /retention-policy` `{retention_days}` | `set_retention_policy` | 200 `{retention_days}` | 400 `invalid_retention_days` (<1); 503 |
| `GET /retention-policy` | `retention_days_for_tenant` | 200 `{retention_days}` | 503 |

Router mounted in `api/v1/__init__.py` with prefix `/data-protection`. The
`DataProtectionService` methods `flush()` but do not `commit()`, so each
write endpoint must `await session.commit()` after a successful service call
(the DI dependency exposes the same request session). Read endpoints do not
commit.

Pydantic schemas in `api/v1/schemas/data_protection.py` (request + response
models, frozen).

## Error Handling

- `LegalHoldBlockedError` → 409 `legal_hold_blocks_erasure`.
- `DataProtectionError` (bad scope, retention < 1) → 400 with a specific code.
- Service None (unconfigured) → 503 `data_protection_not_configured`.
- Missing `principal_id` → 400 `principal_axis_missing` (existing helper).

## Testing Strategy (TDD — failing test first)

`test_data_protection_admin_api.py`:
- 403 without `tenant.privacy.admin` on every endpoint.
- **Erasure round-trip**: encrypt subject data → erase → the data key row is
  gone and decryption raises `DataProtectionError` (data unrecoverable).
- Erasure writes a `completed` `DataProtectionErasureRequestRow`.
- Legal hold blocks erasure → 409 + a `blocked` erasure audit row.
- Create → list shows the hold; release → list no longer shows it; after release,
  erasure of the same subject now succeeds (hold no longer blocks).
- `release_legal_hold` for another tenant's hold → 404 (tenant isolation).
- Retention: set 30 → get returns 30; set 0 → 400.
- 503 when data protection is unconfigured.
- Migration 0068 applies and is reversible (Postgres-gated).

Run from repo root with `TEST_DATABASE_URL` for the Postgres-gated cases.

## Risks

- **Irreversibility**: erasure crypto-shreds permanently. Mitigated by the
  legal-hold gate (blocks erasure under hold), the durable audit row, and the
  dedicated `tenant.privacy.admin` SoD capability (not granted to operators by
  default). Tenant-wide erasure is intentionally not exposed.
- **`has_active_legal_hold` change**: adding the released filter must not break
  existing 1c tests (legal-hold-blocks-purge/DSAR) — they create holds and never
  release, so they remain active. Verified by re-running the 1c suite.
- **Retention only acts on tenants with a policy row**: now operationally
  settable, but tenants without a policy are still never purged. Documented as
  intentional (explicit retention opt-in); a platform default could be a later
  enhancement.
