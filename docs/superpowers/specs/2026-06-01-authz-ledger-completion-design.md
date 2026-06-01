# Spec 1a — Authorization & Ledger Completion

- Date: 2026-06-01
- Status: Approved (design); pending implementation plan
- Phase: 1 (code-level hardening), spec 1a
- Audit findings closed: #5, #22, #26, #80, #81, #83
- Credentials required: none (fully unblocked)
- Approach: A (all four components in one spec, one shared migration)

## Purpose

Close the remaining authorization accountability gaps left after the S-01–S-09
remediation and spec 1b edge-hardening:

1. Observability and audit endpoints are readable by any authenticated tenant
   user, with no role gate differentiating operators from read-only users (#26,
   #80, #81).
2. Any authenticated principal in a tenant can read/write any session via the
   conversation API, even sessions they did not create (#83).
3. The config-change ledger records who proposed and approved a change, but not
   who applied it, leaving the apply action unattributed (#5).
4. Approved change requests have no revocation mechanism; they remain
   indefinitely applicable (#22).

## Non-Goals

- Frontend / command-center workflow for revocation (later spec).
- Policy version binding and cache invalidation (#69, #77) — spec 1d.
- Object-level RBAC on sessions *created by* other principals outside the
  conversation path (e.g., session admin views) — deferred.
- Compliance artifacts (SOC 2, retention) — Phase 4.

## Current State

- `PERMISSION_CAPABILITY_MAP` and `ROLE_CAPABILITY_MAP` are in
  [apps/backend/app/auth/providers/jwt.py:91-112](../../../apps/backend/app/auth/providers/jwt.py).
  Existing domain capabilities: `tenant.config.write`, `tenant.config.approve`,
  `tenant.channel.admin`, `tenant.knowledge.write`, `tenant.policy.write`,
  `tenant.topology.write`, `tenant.execution_governance.write`.
- Observability router ([apps/backend/app/api/v1/routers/observability.py](../../../apps/backend/app/api/v1/routers/observability.py)):
  9 endpoints, all gated only by `require_tenant_scope`. No role/capability gate.
- Audit export router ([apps/backend/app/api/v1/routers/audit_export.py](../../../apps/backend/app/api/v1/routers/audit_export.py)):
  `GET /export` gated by `require_tenant_scope`; `POST /verify` intentionally
  unauthenticated (correct per design) but has no body-size cap beyond the
  global 1 MiB limit.
- Conversation router ([apps/backend/app/api/v1/routers/conversation.py](../../../apps/backend/app/api/v1/routers/conversation.py)):
  `POST /{session_id}/message` and `GET /{session_id}/stream` pass
  `expected_tenant_id` to RLS-guard the DB query, but do not verify that the
  calling principal owns or is assigned to the session. Sessions already store
  `principal_id` in `SessionRecord` ([session/persistence/records.py:33](../../../apps/backend/app/session/persistence/records.py)).
- `TenantConfigChangeRequestRecord` ([tenant/change_requests.py:59](../../../apps/backend/app/tenant/change_requests.py)):
  has `applied_at` but no `applied_by`. The `apply()` service method does not
  accept or record the applier principal. Migration head: `0065`.
- No `REVOKED` status exists on change requests; approved requests stay
  indefinitely applicable.

## Component 1: Domain Capability Gates (#26, #80, #81)

### New capabilities

Two new domain capabilities, following the `tenant.<domain>.<action>` naming
convention:

| Constant | Value | Protects |
|---|---|---|
| `TENANT_OBSERVABILITY_READ_CAPABILITY` | `"tenant.observability.read"` | All 9 `/observability/*` endpoints |
| `TENANT_AUDIT_EXPORT_CAPABILITY` | `"tenant.audit.export"` | `GET /audit/export` |

`POST /audit/verify` remains intentionally unauthenticated. Its body-size cap
(finding #81) is handled by a tighter per-route `RequestBodyLimitMiddleware`
override on the route itself (see below).

### Capability dependency functions

Added to [dependencies/authority.py](../../../apps/backend/app/dependencies/authority.py)
alongside the existing pattern:

```python
TENANT_OBSERVABILITY_READ_CAPABILITY: Final[str] = "tenant.observability.read"
TENANT_AUDIT_EXPORT_CAPABILITY: Final[str] = "tenant.audit.export"

def require_tenant_observability_read(request: Request) -> AuthorityContext:
    ...  # same pattern as require_tenant_config_approve

def require_tenant_audit_export(request: Request) -> AuthorityContext:
    ...
```

Module-level functions (not closures) so `dependency_overrides` work in tests.

### Auth0 role/permission mapping

Added to `ROLE_CAPABILITY_MAP` in
[apps/backend/app/auth/providers/jwt.py](../../../apps/backend/app/auth/providers/jwt.py):

```python
"TenantObserver":   "tenant.observability.read",
"TenantAuditor":    "tenant.audit.export",
```

And to `PERMISSION_CAPABILITY_MAP`:

```python
"read:tenant_observability": "tenant.observability.read",
"read:tenant_audit":         "tenant.audit.export",
```

The `Operator` role already maps to `"operator"` which carries all platform
capabilities; operators retain full access without being explicitly listed in
the new roles.

### Router wiring

**observability.py** — all 9 endpoints replace `require_tenant_scope` with a
composed dependency that requires both the tenant scope AND the new capability:

```python
expected_tenant_id: str = Depends(require_tenant_scope),
_obs_auth: AuthorityContext = Depends(require_tenant_observability_read),
```

**audit_export.py** — `GET /export` adds `require_tenant_audit_export`;
`POST /verify` adds a per-route `Request` body-size cap of **256 KiB** enforced
inline before the HMAC computation:

```python
if len(await request.body()) > 256 * 1024:
    raise HTTPException(status_code=413, detail="audit_export_too_large")
```

This does not replace the global `RequestBodyLimitMiddleware`; it is an
additional, tighter gate specific to the CPU-intensive verify path.

### Governance router

`GET /governance/*` endpoints are already tenant-RLS-scoped and read-only
(decisions, policy chains, evaluation records). These are read-once audit
artifacts that operators review; they are gated at `require_tenant_scope`.
They do NOT get an additional domain capability gate in this spec — object-level
governance RBAC is tracked separately.

## Component 2: Conversation Session Ownership (#83)

### Invariant

A principal may only read or write a session they own (identified by
`session.identity.principal_id == calling_principal_id`). Operators
(`OPERATOR_CAPABILITY`) bypass this check.

Sessions whose `principal_id` is `None` (created by webhook ingress, without a
bound user principal) are pass-through: tenant-scoped RLS still applies, but no
principal check is enforced (no principal to compare against).

### Service changes

`ConversationService.submit_message()` and `ensure_stream_access()` gain:

```python
calling_principal_id: str | None
is_operator: bool = False
```

After fetching the session record, before doing any work:

```python
session_principal = session.identity.principal_id
if (
    session_principal is not None
    and calling_principal_id != session_principal
    and not is_operator
):
    raise ConversationAccessDenied(session_id)
```

### New exception

```python
class ConversationAccessDenied(ConversationServiceError):
    """Raised when a principal attempts to access a session they do not own."""
```

Maps to `403 session_access_denied` in the router's `_http_error` helper.

### Router changes

The conversation router extracts both values from the authority dependency and
threads them into the service:

```python
authority: AuthorityContext = Depends(require_authority),
expected_tenant_id: str = Depends(require_tenant_scope),
```

```python
calling_principal_id=str(authority.principal_id) if authority.principal_id else None,
is_operator=OPERATOR_CAPABILITY in authority.capabilities,
```

No migration required — `SessionRecord.principal_id` already exists in the DB.

## Component 3: Ledger `applied_by` (#5)

### Migration 0066 (partial — see Component 4 for full migration)

```sql
ALTER TABLE tenant_config_change_requests
  ADD COLUMN applied_by TEXT,
  ADD CONSTRAINT chk_applied_by_when_applied
    CHECK (status != 'APPLIED' OR applied_by IS NOT NULL);
```

### Model change

`TenantConfigChangeRequestRecord` gains:

```python
applied_by: str | None = None
```

### Service change

`TenantConfigChangeRequestService.apply()` gains `applied_by: str`:

```python
async def apply(
    self,
    *,
    change_request_id: uuid.UUID | str,
    expected_tenant_id: str,
    applied_by: str,          # ← new
) -> TenantConfigChangeRequestRecord:
```

The `replace(record, ..., applied_at=_utcnow(), applied_by=applied_by)` call
records the applier. If `applied_by` is empty, the service raises
`TenantConfigChangeRequestLifecycleError` before reaching the DB.

### Router change

The apply endpoint passes `str(authority.principal_id)` as `applied_by`. If
the authority has no `principal_id` (should not happen under the bearer +
capability gate), the endpoint rejects with 403.

The existing `require_tenant_config_approve` dependency already ensures the
caller holds `tenant.config.approve`; the `_approver` result now supplies the
principal:

```python
_approver: AuthorityContext = Depends(require_tenant_config_approve),
```

```python
record = await service.apply(
    change_request_id=change_request_id,
    expected_tenant_id=expected_tenant_id,
    applied_by=str(_approver.principal_id),
)
```

## Component 4: Ledger Revocation (#22)

### Full migration 0066

Migration `0066_tenant_config_change_request_revocation` applies all changes
from Components 3 and 4 in one transaction:

```sql
-- Component 3
ALTER TABLE tenant_config_change_requests
  ADD COLUMN applied_by TEXT;

-- Component 4
ALTER TYPE tenant_config_change_request_status ADD VALUE IF NOT EXISTS 'REVOKED';

ALTER TABLE tenant_config_change_requests
  ADD COLUMN revoked_by TEXT,
  ADD COLUMN revoked_at TIMESTAMPTZ;

ALTER TABLE tenant_config_change_requests
  ADD CONSTRAINT chk_applied_by_when_applied
    CHECK (status != 'APPLIED' OR applied_by IS NOT NULL),
  ADD CONSTRAINT chk_revoked_by_when_revoked
    CHECK (status != 'REVOKED' OR revoked_by IS NOT NULL);
```

The migration uses `IF NOT EXISTS` on enum value addition so it is idempotent.
FORCE RLS is already set on this table by migration 0063.

### Status enum

`TenantConfigChangeRequestStatus` gains `REVOKED = "REVOKED"`.

A revoked request is terminal: it cannot be approved, applied, or re-proposed.
The existing `apply()` precondition check adds `REVOKED` to the disallowed set.

### Revoke service method

```python
async def revoke(
    self,
    *,
    change_request_id: uuid.UUID | str,
    expected_tenant_id: str,
    revoked_by: str,
) -> TenantConfigChangeRequestRecord:
```

Business rules:
- Only `APPROVED` status can be revoked. Any other status raises
  `TenantConfigChangeRequestLifecycleError` with a clear message.
- `revoked_by` must be non-empty (same guard as `applied_by`).
- Appends a status operational event (`"change_request.revoked"`).

No `revoked_by != approved_by` constraint: revocation is an undoing action
(different risk profile from approval), so the same principal who approved may
revoke without violating separation-of-duties.

### Revoke router endpoint

```
POST /api/v1/tenant/config/change-requests/{change_request_id}/revoke
```

Capability gate: `require_tenant_config_approve` (same role that approves can
revoke). Returns the updated `TenantConfigChangeRequestResponse`.

### `apply()` defense

```python
if record.status in (
    TenantConfigChangeRequestStatus.REVOKED,
    TenantConfigChangeRequestStatus.APPLIED,
    TenantConfigChangeRequestStatus.REJECTED,
):
    raise TenantConfigChangeRequestLifecycleError(
        f"cannot apply a {record.status.value} change request"
    )
```

## File Structure

**Create:**
- `apps/backend/migrations/versions/0066_tenant_config_change_request_revocation.py`
- `apps/backend/tests/test_authz_domain_capabilities.py`
- `apps/backend/tests/test_conversation_ownership.py`
- `apps/backend/tests/test_ledger_applied_by.py`
- `apps/backend/tests/test_ledger_revocation.py`

**Modify:**
- `apps/backend/app/dependencies/authority.py` — 2 new constants + 2 new dependencies
- `apps/backend/app/auth/providers/jwt.py` — 2 new role entries, 2 new permission entries
- `apps/backend/app/api/v1/routers/observability.py` — add capability dep to all 9 endpoints
- `apps/backend/app/api/v1/routers/audit_export.py` — add capability dep + body cap
- `apps/backend/app/api/v1/routers/conversation.py` — thread principal + operator flag
- `apps/backend/app/services/conversation_service.py` — ownership check + new exception
- `apps/backend/app/tenant/change_requests.py` — `applied_by`, `revoked_by`, `revoked_at`, `REVOKED` status
- `apps/backend/app/services/tenant_config_change_request_service.py` — `apply()` + `revoke()`
- `apps/backend/app/api/v1/routers/tenant.py` — apply endpoint threads `applied_by`; revoke endpoint added

## Testing Strategy (TDD — failing test first for every step)

**`test_authz_domain_capabilities.py`**
- `tenant.observability.read` absent → 403 on metrics/DLQ/traces/alerts
- `tenant.observability.read` present → 200
- `tenant.audit.export` absent → 403 on export
- `tenant.audit.export` present → 200
- `/audit/verify` with body > 256 KiB → 413 (no auth required)
- Operator capability bypasses all capability gates
- ROLE_CAPABILITY_MAP: `TenantObserver` maps to `tenant.observability.read`
- PERMISSION_CAPABILITY_MAP entries present

**`test_conversation_ownership.py`**
- Principal A owns session → A can submit message
- Principal A owns session → Principal B (non-operator) gets 403
- Principal A owns session → Operator B can submit (operator bypass)
- Session with no principal_id → any tenant principal can access
- Anonymous authority (no principal_id) → treated as non-owner for owned sessions

**`test_ledger_applied_by.py`**
- `apply()` without `applied_by` → `TenantConfigChangeRequestLifecycleError`
- `apply()` with `applied_by` → record has `applied_by` set
- DB CHECK constraint holds (requires Postgres, marks `@pytest.mark.requires_postgres`)
- Router endpoint threads `authority.principal_id` as `applied_by`

**`test_ledger_revocation.py`**
- Revoke `APPROVED` → record becomes `REVOKED` with `revoked_by` + `revoked_at`
- Revoke `PROPOSED` → `TenantConfigChangeRequestLifecycleError`
- Revoke `APPLIED` → `TenantConfigChangeRequestLifecycleError`
- Apply `REVOKED` → `TenantConfigChangeRequestLifecycleError`
- Revoke requires `tenant.config.approve` capability → 403 without it
- Status event `change_request.revoked` is appended

Run from repo root: `python -m pytest apps/backend/tests/...`

## Risks

- **Enum migration on Postgres**: adding a value to a `pg_enum` type is
  DDL that does not require a table rewrite, but must run outside a transaction
  in older Postgres versions. The migration uses `ALTER TYPE ... ADD VALUE IF
  NOT EXISTS` which is safe in Postgres 16 (the project's production version).
- **Existing applied records**: the `applied_by NOT NULL` constraint is
  `CHECK (status != 'APPLIED' OR applied_by IS NOT NULL)` which allows existing
  APPLIED rows (that have no `applied_by`) to remain valid. New applies are
  enforced at the service layer; the constraint is belt-and-suspenders.
- **Session ownership for operator-created sessions**: the `principal_id` field
  may be `None` for sessions created by background workers. The pass-through
  rule (no check when `principal_id IS NULL`) is intentional and correct.
- **Observability 403 breaking the command center**: the command center
  currently reads observability data. Operators hold `OPERATOR_CAPABILITY`
  which bypasses the domain gate — so operator-authenticated CC sessions are
  unaffected. Non-operator CC users who currently read observability will see
  403s until the Auth0 role assignment is updated (this is the correct behavior
  — they should not have had access).
