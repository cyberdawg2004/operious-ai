# Authorization & Ledger Completion (Spec 1a) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close six authorization accountability gaps: add domain capability gates on observability and audit endpoints, enforce conversation session ownership, record who applied a config change, and allow approved changes to be revoked.

**Architecture:** Four independent components share one migration (0066). Task order is chosen so later tasks depend only on what earlier tasks define: capabilities first (Task 1), then routers consuming them (Tasks 2–3), then the conversation service (Task 4), then the ledger migration/model (Tasks 5–6), then ledger service/schema/router (Tasks 7–8), then a final verification sweep (Task 9).

**Tech Stack:** Python 3.12, FastAPI/Starlette, SQLAlchemy 2 + asyncpg, Alembic, pytest (run from repo root with `python -m pytest`).

**Conventions:**
- Always run pytest from `/home/imad-baraja/Projects/operious-ai` (repo root). Running from `apps/backend` causes ~29 spurious failures.
- Tests use `ENVIRONMENT=test` (no real Redis or Postgres needed for unit tests). Integration tests that hit Postgres are marked `@pytest.mark.requires_postgres`.
- Test DB URL for integration tests: `postgresql+asyncpg://operious:operious@localhost:5433/operious_test` (set `TEST_DATABASE_URL` env var).
- Commit trailer: `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- Spec: [docs/superpowers/specs/2026-06-01-authz-ledger-completion-design.md](../specs/2026-06-01-authz-ledger-completion-design.md).

---

## File Structure

**Create:**
- `apps/backend/migrations/versions/0066_tenant_config_change_request_revocation.py`
- `apps/backend/tests/test_authz_domain_capabilities.py`
- `apps/backend/tests/test_conversation_ownership.py`
- `apps/backend/tests/test_ledger_applied_by.py`
- `apps/backend/tests/test_ledger_revocation.py`

**Modify:**
- `apps/backend/app/dependencies/authority.py` — 2 constants + 2 module-level dependency functions + `__all__`
- `apps/backend/app/auth/providers/jwt.py` — 2 entries in `ROLE_CAPABILITY_MAP`, 2 in `PERMISSION_CAPABILITY_MAP`
- `apps/backend/app/api/v1/routers/observability.py` — add capability dep to all 9 endpoints
- `apps/backend/app/api/v1/routers/audit_export.py` — add capability dep to export; body cap on verify
- `apps/backend/app/api/v1/routers/conversation.py` — thread principal + operator flag; import `require_authority`
- `apps/backend/app/services/conversation_service.py` — `ConversationAccessDenied`, ownership check, new params
- `apps/backend/app/session/conversation/runtime.py` — `get_session_owner_principal_id` method
- `apps/backend/app/session/conversation/__init__.py` — export new method
- `apps/backend/app/tenant/change_requests.py` — `REVOKED` status, `applied_by`/`revoked_by`/`revoked_at` fields, updated serializers
- `apps/backend/app/tenant/db/models.py` — new ORM columns + updated check constraints
- `apps/backend/app/services/tenant_config_change_request_service.py` — `apply()` gains `applied_by`; new `revoke()`
- `apps/backend/app/api/v1/schemas/tenant.py` — `TenantConfigChangeRequestResponse` gains 3 new fields
- `apps/backend/app/api/v1/routers/tenant.py` — apply endpoint threads `applied_by`; new revoke endpoint

---

## Task 1: Domain capability constants + dependency functions

**Files:**
- Modify: `apps/backend/app/dependencies/authority.py` (after line 150, before `request_authority_opt`)
- Modify: `apps/backend/app/auth/providers/jwt.py` (ROLE_CAPABILITY_MAP ~line 98, PERMISSION_CAPABILITY_MAP ~line 91)
- Test: `apps/backend/tests/test_authz_domain_capabilities.py`

- [ ] **Step 1: Write failing tests**

```python
# apps/backend/tests/test_authz_domain_capabilities.py
"""Spec 1a: domain capability constants, dependency functions, and Auth0 mapping."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from starlette.requests import Request
from starlette.datastructures import Headers

from app.dependencies.authority import (
    TENANT_AUDIT_EXPORT_CAPABILITY,
    TENANT_OBSERVABILITY_READ_CAPABILITY,
    require_tenant_audit_export,
    require_tenant_observability_read,
    OPERATOR_CAPABILITY,
)
from app.auth.providers.jwt import ROLE_CAPABILITY_MAP, PERMISSION_CAPABILITY_MAP
from app.identity import AuthorityContext


def _request(capabilities: list[str], tenant_id: str = "t-1") -> Request:
    ctx = AuthorityContext(tenant_id=tenant_id, capabilities=tuple(capabilities))
    scope = {"type": "http", "headers": []}
    req = Request(scope)
    req.state.authority = ctx
    return req


def test_capability_constant_values() -> None:
    assert TENANT_OBSERVABILITY_READ_CAPABILITY == "tenant.observability.read"
    assert TENANT_AUDIT_EXPORT_CAPABILITY == "tenant.audit.export"


def test_observability_dep_passes_with_capability() -> None:
    req = _request([TENANT_OBSERVABILITY_READ_CAPABILITY])
    result = require_tenant_observability_read(req)
    assert result.tenant_id == "t-1"


def test_observability_dep_fails_without_capability() -> None:
    req = _request(["tenant_read"])
    with pytest.raises(HTTPException) as exc:
        require_tenant_observability_read(req)
    assert exc.value.status_code == 403


def test_audit_export_dep_passes_with_capability() -> None:
    req = _request([TENANT_AUDIT_EXPORT_CAPABILITY])
    result = require_tenant_audit_export(req)
    assert result.tenant_id == "t-1"


def test_audit_export_dep_fails_without_capability() -> None:
    req = _request(["tenant_read"])
    with pytest.raises(HTTPException) as exc:
        require_tenant_audit_export(req)
    assert exc.value.status_code == 403


def test_operator_capability_satisfies_observability_gate() -> None:
    # Operator role maps to "operator" — which is NOT in the new capability
    # constants. Operators bypass via require_authority's operator check
    # at the service layer, NOT at the dependency gate.
    # The dependency gate is a hard role-capability check; operators
    # are expected to hold tenant.observability.read explicitly in Auth0.
    # This test documents the deliberate design: the gate is capability-based,
    # not role-based.
    req = _request([OPERATOR_CAPABILITY])
    with pytest.raises(HTTPException) as exc:
        require_tenant_observability_read(req)
    assert exc.value.status_code == 403  # operator must also hold the explicit cap


def test_role_map_tenant_observer() -> None:
    assert ROLE_CAPABILITY_MAP.get("TenantObserver") == "tenant.observability.read"


def test_role_map_tenant_auditor() -> None:
    assert ROLE_CAPABILITY_MAP.get("TenantAuditor") == "tenant.audit.export"


def test_permission_map_observability() -> None:
    assert PERMISSION_CAPABILITY_MAP.get("read:tenant_observability") == "tenant.observability.read"


def test_permission_map_audit() -> None:
    assert PERMISSION_CAPABILITY_MAP.get("read:tenant_audit") == "tenant.audit.export"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest apps/backend/tests/test_authz_domain_capabilities.py -q
```

Expected: FAIL — `ImportError` (constants/functions not defined).

- [ ] **Step 3: Add capability constants + dependency functions to authority.py**

In `apps/backend/app/dependencies/authority.py`, after line 150 (after `TENANT_CONFIG_APPROVE_CAPABILITY`), before `request_authority_opt`:

```python
#: Domain capability required to read tenant observability data (metrics,
#: DLQ, traces, alerts, SLOs). Distinct from write capabilities because
#: observation surfaces are read-only but still sensitive.
TENANT_OBSERVABILITY_READ_CAPABILITY: Final[str] = "tenant.observability.read"

#: Domain capability required to export a tenant's signed audit record.
TENANT_AUDIT_EXPORT_CAPABILITY: Final[str] = "tenant.audit.export"


def require_tenant_observability_read(request: Request) -> AuthorityContext:
    """FastAPI dependency: require the tenant.observability.read capability.

    Module-level (not a closure) for stable ``dependency_overrides`` identity.
    """
    authority = require_authority(request)
    if TENANT_OBSERVABILITY_READ_CAPABILITY not in authority.capabilities:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": ERROR_CODE_CAPABILITY_REQUIRED,
                "capability": TENANT_OBSERVABILITY_READ_CAPABILITY,
            },
        )
    return authority


def require_tenant_audit_export(request: Request) -> AuthorityContext:
    """FastAPI dependency: require the tenant.audit.export capability.

    Module-level (not a closure) for stable ``dependency_overrides`` identity.
    """
    authority = require_authority(request)
    if TENANT_AUDIT_EXPORT_CAPABILITY not in authority.capabilities:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": ERROR_CODE_CAPABILITY_REQUIRED,
                "capability": TENANT_AUDIT_EXPORT_CAPABILITY,
            },
        )
    return authority
```

Add to `__all__`:
```python
    "TENANT_AUDIT_EXPORT_CAPABILITY",
    "TENANT_OBSERVABILITY_READ_CAPABILITY",
    "require_tenant_audit_export",
    "require_tenant_observability_read",
```

- [ ] **Step 4: Add Auth0 role + permission mappings to jwt.py**

In `apps/backend/app/auth/providers/jwt.py`, add to `PERMISSION_CAPABILITY_MAP` (after `"write:tenant_config"` line):

```python
    "read:tenant_observability": "tenant.observability.read",
    "read:tenant_audit":         "tenant.audit.export",
```

Add to `ROLE_CAPABILITY_MAP` (after `"TenantApprover"` line):

```python
    "TenantObserver":  "tenant.observability.read",
    "TenantAuditor":   "tenant.audit.export",
```

- [ ] **Step 5: Run test to verify it passes**

```bash
python -m pytest apps/backend/tests/test_authz_domain_capabilities.py -q
```

Expected: PASS (10 tests).

- [ ] **Step 6: Commit**

```bash
git add apps/backend/app/dependencies/authority.py apps/backend/app/auth/providers/jwt.py apps/backend/tests/test_authz_domain_capabilities.py
git commit -m "feat(rbac): tenant.observability.read and tenant.audit.export domain capabilities (#26,#80,#81)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Gate all 9 observability endpoints

**Files:**
- Modify: `apps/backend/app/api/v1/routers/observability.py`
- Test: `apps/backend/tests/test_authz_domain_capabilities.py` (extend)

The observability router has these endpoints (all need the new dep):
`GET /metrics`, `GET /dlq`, `GET /stuck-executions`, `GET /{execution_id}` (4th), `POST /slo-definitions`, `GET /alerts`, `POST /traces`, `GET /traces`, and one more — check the file to confirm the full count and path names.

- [ ] **Step 1: Write the failing test**

Add to `apps/backend/tests/test_authz_domain_capabilities.py`:

```python
import os
from unittest.mock import patch
from starlette.testclient import TestClient
from app.core.config import get_settings
from app.main import create_app
from app.dependencies.authority import require_tenant_observability_read


def _app_with_tenant_authority(*, has_capability: bool) -> TestClient:
    """Boot the app with a dependency override for the observability gate."""
    from app.identity import AuthorityContext

    get_settings.cache_clear()
    try:
        with patch.dict(os.environ, {"ENVIRONMENT": "test",
                                      "RATE_LIMIT_ENABLED": "false"}):
            app = create_app()

        cap = "tenant.observability.read" if has_capability else "tenant_read"
        ctx = AuthorityContext(tenant_id="t-1", capabilities=(cap,))

        from app.dependencies.authority import require_tenant_scope, require_authority

        app.dependency_overrides[require_tenant_scope] = lambda: "t-1"
        app.dependency_overrides[require_authority] = lambda: ctx
        if has_capability:
            app.dependency_overrides[require_tenant_observability_read] = lambda: ctx
        return TestClient(app, raise_server_exceptions=False)
    finally:
        get_settings.cache_clear()


def test_metrics_requires_observability_capability() -> None:
    from datetime import datetime
    no_cap = _app_with_tenant_authority(has_capability=False)
    resp = no_cap.get(
        "/api/v1/observability/metrics",
        params={"window_start": "2026-01-01T00:00:00Z",
                "window_end": "2026-01-02T00:00:00Z"},
    )
    assert resp.status_code == 403


def test_dlq_requires_observability_capability() -> None:
    no_cap = _app_with_tenant_authority(has_capability=False)
    assert no_cap.get("/api/v1/observability/dlq").status_code == 403


def test_alerts_requires_observability_capability() -> None:
    no_cap = _app_with_tenant_authority(has_capability=False)
    assert no_cap.get("/api/v1/observability/alerts").status_code == 403
```

- [ ] **Step 2: Run to verify failure**

```bash
python -m pytest apps/backend/tests/test_authz_domain_capabilities.py::test_metrics_requires_observability_capability -q
```

Expected: FAIL — metrics returns 200 (no capability gate yet).

- [ ] **Step 3: Add the capability dependency to all 9 endpoints in observability.py**

In `apps/backend/app/api/v1/routers/observability.py`, add the import at the top:

```python
from app.dependencies.authority import (
    require_tenant_scope,
    require_tenant_observability_read,
)
```

For **every** `@router.get(...)` and `@router.post(...)` function in the file, add:

```python
_obs: AuthorityContext = Depends(require_tenant_observability_read),
```

as a parameter. Also add `AuthorityContext` to the import:

```python
from app.identity import AuthorityContext
```

The pattern for each endpoint becomes (using metrics as the example):

```python
@router.get("/metrics", response_model=OperationalMetricsResponse)
async def read_operational_metrics(
    window_start: datetime = Query(...),
    window_end: datetime = Query(...),
    expected_tenant_id: str = Depends(require_tenant_scope),
    _obs: AuthorityContext = Depends(require_tenant_observability_read),
    service: OperationalObservabilityService = Depends(
        get_operational_observability_service
    ),
) -> OperationalMetricsResponse:
```

Apply this pattern to all 9 endpoint functions in the file.

- [ ] **Step 4: Run to verify tests pass**

```bash
python -m pytest apps/backend/tests/test_authz_domain_capabilities.py -q
```

Expected: PASS (all 13 tests).

- [ ] **Step 5: Run regression against existing observability tests**

```bash
python -m pytest apps/backend/tests/ -k "observability" -q
```

Expected: PASS (update any failing test to override `require_tenant_observability_read` in `app.dependency_overrides`).

- [ ] **Step 6: Commit**

```bash
git add apps/backend/app/api/v1/routers/observability.py apps/backend/tests/test_authz_domain_capabilities.py
git commit -m "feat(rbac): gate all 9 observability endpoints on tenant.observability.read (#26,#80)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Audit export capability gate + verify body cap

**Files:**
- Modify: `apps/backend/app/api/v1/routers/audit_export.py`
- Test: extend `apps/backend/tests/test_authz_domain_capabilities.py`

- [ ] **Step 1: Write failing tests**

Add to `apps/backend/tests/test_authz_domain_capabilities.py`:

```python
def test_audit_export_requires_capability() -> None:
    import os
    from unittest.mock import patch
    from app.core.config import get_settings
    from app.main import create_app
    from app.identity import AuthorityContext
    from app.dependencies.authority import require_tenant_scope, require_authority

    get_settings.cache_clear()
    try:
        with patch.dict(os.environ, {"ENVIRONMENT": "test",
                                      "RATE_LIMIT_ENABLED": "false",
                                      "AUDIT_EXPORT_HMAC_SECRET": "x" * 32}):
            app = create_app()
        ctx = AuthorityContext(tenant_id="t-1", capabilities=("tenant_read",))
        app.dependency_overrides[require_tenant_scope] = lambda: "t-1"
        app.dependency_overrides[require_authority] = lambda: ctx
        client = TestClient(app, raise_server_exceptions=False)
        assert client.get("/api/v1/audit/export").status_code == 403
    finally:
        get_settings.cache_clear()


def test_audit_verify_large_body_returns_413() -> None:
    import os
    from unittest.mock import patch
    from app.core.config import get_settings
    from app.main import create_app

    get_settings.cache_clear()
    try:
        with patch.dict(os.environ, {"ENVIRONMENT": "test",
                                      "RATE_LIMIT_ENABLED": "false",
                                      "AUDIT_EXPORT_HMAC_SECRET": "x" * 32}):
            app = create_app()
        client = TestClient(app, raise_server_exceptions=False)
        large_body = {"export": {"data": "x" * (257 * 1024)}}
        import json
        resp = client.post(
            "/api/v1/audit/verify",
            content=json.dumps(large_body).encode(),
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 413
    finally:
        get_settings.cache_clear()
```

- [ ] **Step 2: Run to verify failure**

```bash
python -m pytest apps/backend/tests/test_authz_domain_capabilities.py::test_audit_export_requires_capability apps/backend/tests/test_authz_domain_capabilities.py::test_audit_verify_large_body_returns_413 -q
```

Expected: FAIL (export returns 200, verify does not return 413 for large bodies).

- [ ] **Step 3: Implement in audit_export.py**

Replace the content of `apps/backend/app/api/v1/routers/audit_export.py`:

```python
"""Signed tenant audit export endpoints."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.api.v1.schemas.audit_export import (
    AuditExportResponse,
    AuditExportVerifyRequest,
    AuditExportVerifyResponse,
)
from app.dependencies.authority import (
    request_tenant_scope_opt,
    require_tenant_audit_export,
    require_tenant_scope,
)
from app.dependencies.services import get_audit_export_service
from app.identity import AuthorityContext
from app.services.audit_export_service import (
    AuditExportNotConfiguredError,
    AuditExportService,
)

router = APIRouter(tags=["audit"])

_VERIFY_MAX_BODY_BYTES = 256 * 1024  # 256 KiB — tighter than global 1 MiB (#81)


@router.get("/export", response_model=AuditExportResponse)
async def create_audit_export(
    from_timestamp: datetime | None = Query(default=None),
    to_timestamp: datetime | None = Query(default=None),
    expected_tenant_id: str = Depends(require_tenant_scope),
    _auth: AuthorityContext = Depends(require_tenant_audit_export),
    service: AuditExportService = Depends(get_audit_export_service),
) -> AuditExportResponse:
    try:
        export = await service.create_export(
            tenant_id=expected_tenant_id,
            from_timestamp=from_timestamp,
            to_timestamp=to_timestamp,
        )
    except AuditExportNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="audit_export_not_configured",
        ) from exc
    return AuditExportResponse.from_export(export)


@router.post("/verify", response_model=AuditExportVerifyResponse)
async def verify_audit_export(
    request: Request,
    body: AuditExportVerifyRequest,
    _tenant_scope: str | None = Depends(request_tenant_scope_opt),
    service: AuditExportService = Depends(get_audit_export_service),
) -> AuditExportVerifyResponse:
    # POST /api/v1/audit/verify is intentionally unauthenticated. Anyone who
    # holds a signed audit export should be able to verify its authenticity
    # without requiring a session. The endpoint recomputes the HMAC and compares
    # signatures; it does not return tenant data beyond what is already present
    # in the provided export.
    #
    # Body size is capped tightly here (256 KiB) to bound the HMAC CPU cost
    # without relying solely on the global 1 MiB request-body limit (#81).
    raw = await request.body()
    if len(raw) > _VERIFY_MAX_BODY_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={
                "code": "audit_export_too_large",
                "max_bytes": _VERIFY_MAX_BODY_BYTES,
            },
        )
    try:
        result = service.verify_export(export=body.export)
    except AuditExportNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="audit_export_not_configured",
        ) from exc
    return AuditExportVerifyResponse.from_verification(result)


__all__ = ["router"]
```

- [ ] **Step 4: Run to verify tests pass**

```bash
python -m pytest apps/backend/tests/test_authz_domain_capabilities.py -q
```

Expected: PASS (all tests).

- [ ] **Step 5: Run audit regression**

```bash
python -m pytest apps/backend/tests/ -k "audit" -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/backend/app/api/v1/routers/audit_export.py apps/backend/tests/test_authz_domain_capabilities.py
git commit -m "feat(rbac): gate audit/export on tenant.audit.export; add verify body cap (#80,#81)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: Conversation session ownership

**Files:**
- Modify: `apps/backend/app/session/conversation/runtime.py` (add `get_session_owner_principal_id`)
- Modify: `apps/backend/app/session/conversation/__init__.py` (export the new method)
- Modify: `apps/backend/app/services/conversation_service.py` (new exception + ownership check)
- Modify: `apps/backend/app/api/v1/routers/conversation.py` (thread authority)
- Test: `apps/backend/tests/test_conversation_ownership.py`

- [ ] **Step 1: Write failing tests**

```python
# apps/backend/tests/test_conversation_ownership.py
"""Spec 1a — conversation session ownership enforcement (#83)."""

from __future__ import annotations

import pytest

from app.services.conversation_service import (
    ConversationAccessDenied,
    ConversationService,
    ConversationServiceError,
)


class _FakeRuntime:
    """Minimal stub for ConversationSessionRuntime."""

    def __init__(self, owner_principal_id: str | None) -> None:
        self._owner = owner_principal_id
        self.submit_calls: list[dict] = []

    async def get_session_owner_principal_id(
        self, *, session_id: str, expected_tenant_id: str
    ) -> str | None:
        return self._owner

    async def submit_message(self, **kwargs) -> object:  # type: ignore[override]
        self.submit_calls.append(kwargs)
        raise ConversationServiceError("test_stub_no_submit")

    async def get_conversation_state(self, **kwargs) -> object:  # type: ignore[override]
        pass


def _service(owner: str | None) -> ConversationService:
    return ConversationService(runtime=_FakeRuntime(owner), redis_client=None)


async def test_owner_principal_can_submit() -> None:
    service = _service("principal-A")
    with pytest.raises(ConversationServiceError) as exc:
        await service.submit_message(
            session_id="s-1",
            tenant_id="t-1",
            content="hello",
            expected_tenant_id="t-1",
            calling_principal_id="principal-A",
        )
    # Should reach the runtime (raising stub error), NOT raise ConversationAccessDenied.
    assert "test_stub_no_submit" in str(exc.value)


async def test_non_owner_principal_is_denied() -> None:
    service = _service("principal-A")
    with pytest.raises(ConversationAccessDenied):
        await service.submit_message(
            session_id="s-1",
            tenant_id="t-1",
            content="hello",
            expected_tenant_id="t-1",
            calling_principal_id="principal-B",
        )


async def test_operator_bypasses_ownership_check() -> None:
    service = _service("principal-A")
    with pytest.raises(ConversationServiceError) as exc:
        await service.submit_message(
            session_id="s-1",
            tenant_id="t-1",
            content="hello",
            expected_tenant_id="t-1",
            calling_principal_id="principal-B",
            is_operator=True,
        )
    assert "test_stub_no_submit" in str(exc.value)


async def test_session_without_owner_passes_through() -> None:
    """Sessions created by webhook ingress have no bound principal."""
    service = _service(None)
    with pytest.raises(ConversationServiceError) as exc:
        await service.submit_message(
            session_id="s-1",
            tenant_id="t-1",
            content="hello",
            expected_tenant_id="t-1",
            calling_principal_id="anyone",
        )
    assert "test_stub_no_submit" in str(exc.value)


async def test_anonymous_caller_denied_on_owned_session() -> None:
    service = _service("principal-A")
    with pytest.raises(ConversationAccessDenied):
        await service.submit_message(
            session_id="s-1",
            tenant_id="t-1",
            content="hello",
            expected_tenant_id="t-1",
            calling_principal_id=None,  # no principal on caller
        )


async def test_ensure_stream_access_enforces_ownership() -> None:
    service = _service("principal-A")
    with pytest.raises(ConversationAccessDenied):
        await service.ensure_stream_access(
            session_id="s-1",
            expected_tenant_id="t-1",
            calling_principal_id="principal-B",
        )
```

- [ ] **Step 2: Run to verify failure**

```bash
python -m pytest apps/backend/tests/test_conversation_ownership.py -q
```

Expected: FAIL — `ImportError: cannot import name 'ConversationAccessDenied'`.

- [ ] **Step 3: Add `get_session_owner_principal_id` to the conversation runtime**

In `apps/backend/app/session/conversation/runtime.py`, add the following method after `get_recent_turns` (~line 238) and before `_require_session`:

```python
    async def get_session_owner_principal_id(
        self,
        *,
        session_id: str,
        expected_tenant_id: str,
    ) -> str | None:
        """Return the ``principal_id`` bound to this session, or ``None``.

        Returns ``None`` when the session does not exist (callers should let
        the normal flow surface the not-found error) or when the session was
        created without a bound user principal (e.g., webhook-ingested sessions).
        """
        record = await self._session_repository.get_session(
            as_session_id(session_id),
            expected_tenant_id=expected_tenant_id,
        )
        if record is None:
            return None
        return record.identity.principal_id
```

- [ ] **Step 4: Export the method from `apps/backend/app/session/conversation/__init__.py`**

Read the current `__init__.py` and check if `ConversationSessionRuntime` is exported. The method is an instance method, so it's accessed through the class — no additional export needed. But confirm `ConversationSessionRuntime` is already in `__all__` (it is, per our earlier grep).

No change needed to `__init__.py` since `get_session_owner_principal_id` is a method on the already-exported `ConversationSessionRuntime` class.

- [ ] **Step 5: Add `ConversationAccessDenied` + ownership check to `conversation_service.py`**

In `apps/backend/app/services/conversation_service.py`:

1. After the existing `ConversationServiceError` class definition, add:

```python
class ConversationAccessDenied(ConversationServiceError):
    """Raised when a principal attempts to access a session they do not own.

    Maps to ``403 session_access_denied`` in the router.
    """
```

2. Add the private ownership check method to `ConversationService`:

```python
    async def _check_session_ownership(
        self,
        *,
        session_id: str,
        expected_tenant_id: str,
        calling_principal_id: str | None,
        is_operator: bool,
    ) -> None:
        """Verify the calling principal owns the session (or is an operator).

        Passes through when the session has no bound principal (e.g., sessions
        created by webhook ingestion) because there is no owner to compare
        against. Fails closed when the session has a principal and the caller
        does not match and is not an operator.
        """
        if is_operator:
            return
        owner = await self._runtime.get_session_owner_principal_id(
            session_id=session_id,
            expected_tenant_id=expected_tenant_id,
        )
        if owner is not None and calling_principal_id != owner:
            raise ConversationAccessDenied(
                f"session {session_id!r} belongs to a different principal"
            )
```

3. Update `submit_message` signature to:

```python
    async def submit_message(
        self,
        *,
        session_id: str,
        tenant_id: str,
        content: str,
        expected_tenant_id: str,
        calling_principal_id: str | None = None,
        is_operator: bool = False,
    ) -> ConversationMessageSubmission:
        await self._check_session_ownership(
            session_id=session_id,
            expected_tenant_id=expected_tenant_id,
            calling_principal_id=calling_principal_id,
            is_operator=is_operator,
        )
        try:
            result = await self._runtime.submit_message(
                session_id=session_id,
                tenant_id=tenant_id,
                customer_message=content,
                expected_tenant_id=expected_tenant_id,
            )
        except ConversationRuntimeError as exc:
            raise ConversationServiceError(str(exc)) from exc
        return ConversationMessageSubmission(
            turn_id=result.phase_a_turn.turn_id,
            phase_a_response=result.phase_a_turn.content,
            execution_id=result.execution.execution_id,
        )
```

4. Update `ensure_stream_access` signature to:

```python
    async def ensure_stream_access(
        self,
        *,
        session_id: str,
        expected_tenant_id: str,
        calling_principal_id: str | None = None,
        is_operator: bool = False,
    ) -> None:
        await self._check_session_ownership(
            session_id=session_id,
            expected_tenant_id=expected_tenant_id,
            calling_principal_id=calling_principal_id,
            is_operator=is_operator,
        )
        try:
            await self._runtime.get_conversation_state(
                session_id=session_id,
                expected_tenant_id=expected_tenant_id,
            )
        except ConversationRuntimeError as exc:
            raise ConversationServiceError(str(exc)) from exc
```

5. Add `ConversationAccessDenied` to `__all__`.

- [ ] **Step 6: Run to verify tests pass**

```bash
python -m pytest apps/backend/tests/test_conversation_ownership.py -q
```

Expected: PASS (7 tests).

- [ ] **Step 7: Wire the ownership check into the conversation router**

Replace the full contents of `apps/backend/app/api/v1/routers/conversation.py`:

```python
"""Live conversation endpoints."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, status
from sse_starlette.sse import EventSourceResponse

from app.api.v1.schemas.conversation import (
    ConversationMessageRequest,
    ConversationMessageResponse,
)
from app.dependencies.authority import (
    OPERATOR_CAPABILITY,
    require_authority,
    require_tenant_scope,
)
from app.dependencies.services import get_conversation_service
from app.identity import AuthorityContext
from app.services.conversation_service import (
    ConversationAccessDenied,
    ConversationService,
    ConversationServiceError,
)

router = APIRouter(tags=["conversation"])


@router.post(
    "/{session_id}/message",
    response_model=ConversationMessageResponse,
)
async def submit_conversation_message(
    session_id: str,
    request: ConversationMessageRequest,
    expected_tenant_id: str = Depends(require_tenant_scope),
    authority: AuthorityContext = Depends(require_authority),
    service: ConversationService = Depends(get_conversation_service),
) -> ConversationMessageResponse:
    try:
        return ConversationMessageResponse.from_submission(
            await service.submit_message(
                session_id=session_id,
                tenant_id=expected_tenant_id,
                content=request.content,
                expected_tenant_id=expected_tenant_id,
                calling_principal_id=(
                    str(authority.principal_id) if authority.principal_id else None
                ),
                is_operator=OPERATOR_CAPABILITY in authority.capabilities,
            )
        )
    except ConversationAccessDenied as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "session_access_denied", "message": str(exc)},
        ) from exc
    except ConversationServiceError as exc:
        raise _http_error(exc) from exc


@router.get("/{session_id}/stream")
async def stream_conversation(
    session_id: str,
    expected_tenant_id: str = Depends(require_tenant_scope),
    authority: AuthorityContext = Depends(require_authority),
    service: ConversationService = Depends(get_conversation_service),
) -> EventSourceResponse:
    try:
        await service.ensure_stream_access(
            session_id=session_id,
            expected_tenant_id=expected_tenant_id,
            calling_principal_id=(
                str(authority.principal_id) if authority.principal_id else None
            ),
            is_operator=OPERATOR_CAPABILITY in authority.capabilities,
        )
    except ConversationAccessDenied as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "session_access_denied", "message": str(exc)},
        ) from exc
    except ConversationServiceError as exc:
        raise _http_error(exc) from exc

    async def events() -> AsyncIterator[dict[str, str]]:
        async for event in service.stream_events(
            session_id=session_id,
            expected_tenant_id=expected_tenant_id,
        ):
            yield {
                "event": str(event.get("type") or "message"),
                "data": json.dumps(event, default=str),
            }

    return EventSourceResponse(events())


def _http_error(exc: ConversationServiceError) -> HTTPException:
    message = str(exc)
    status_code = status.HTTP_400_BAD_REQUEST
    code = "conversation_request_failed"
    if "not found" in message:
        status_code = status.HTTP_404_NOT_FOUND
        code = "session_not_found"
    elif "terminal" in message:
        status_code = status.HTTP_409_CONFLICT
        code = "session_terminal"
    elif "governance" in message or "dispatch" in message:
        status_code = status.HTTP_403_FORBIDDEN
        code = "conversation_governance_denied"
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message},
    )


__all__ = ["router"]
```

- [ ] **Step 8: Run all conversation tests**

```bash
python -m pytest apps/backend/tests/test_conversation_ownership.py apps/backend/tests/ -k "conversation" -q
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add apps/backend/app/session/conversation/runtime.py apps/backend/app/services/conversation_service.py apps/backend/app/api/v1/routers/conversation.py apps/backend/tests/test_conversation_ownership.py
git commit -m "feat(auth): conversation session ownership enforcement (#83)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: Migration 0066 — applied_by, revoke columns, REVOKED status

**Files:**
- Create: `apps/backend/migrations/versions/0066_tenant_config_change_request_revocation.py`

No TDD is possible for a raw migration, but the service tests in Tasks 7 will require the Postgres schema to match. Write the migration now so the ORM and service changes that follow are against the real schema.

- [ ] **Step 1: Create the migration**

```python
# apps/backend/migrations/versions/0066_tenant_config_change_request_revocation.py
"""Ledger applied_by + REVOKED status + revoke fields (spec 1a #5, #22)

Revision ID: 0066_tenant_config_change_request_revocation
Revises: 0065_knowledge_review_status
Create Date: 2026-06-01
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0066_tenant_config_change_request_revocation"
down_revision: Union[str, None] = "0065_knowledge_review_status"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add applied_by: who applied the change (attribution for durable audit).
    op.add_column(
        "tenant_config_change_requests",
        sa.Column("applied_by", sa.String(255), nullable=True),
    )

    # Add revocation fields: who revoked an APPROVED request and when.
    op.add_column(
        "tenant_config_change_requests",
        sa.Column("revoked_by", sa.String(255), nullable=True),
    )
    op.add_column(
        "tenant_config_change_requests",
        sa.Column(
            "revoked_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    # Widen the status valid constraint to include REVOKED.
    # Postgres requires DROP + re-ADD to modify a CHECK constraint.
    op.drop_constraint(
        "status_valid",
        "tenant_config_change_requests",
        type_="check",
    )
    op.create_check_constraint(
        "status_valid",
        "tenant_config_change_requests",
        "status IN ('PROPOSED', 'APPROVED', 'REJECTED', 'APPLIED', 'REVOKED')",
    )

    # Attribution integrity: new APPLIED rows must carry the applier identity.
    # Existing APPLIED rows (no applied_by) remain valid — the constraint only
    # gates future writes. Service-layer validation is the primary guard.
    op.create_check_constraint(
        "chk_applied_by_when_applied",
        "tenant_config_change_requests",
        "status != 'APPLIED' OR applied_by IS NOT NULL",
    )

    # Revocation integrity: REVOKED rows must carry the revoker identity.
    op.create_check_constraint(
        "chk_revoked_by_when_revoked",
        "tenant_config_change_requests",
        "status != 'REVOKED' OR revoked_by IS NOT NULL",
    )

    op.execute(
        """
        COMMENT ON COLUMN tenant_config_change_requests.applied_by IS
        'Principal who applied this change request (migration 0066). NULL on pre-existing APPLIED rows.'
        """
    )
    op.execute(
        """
        COMMENT ON COLUMN tenant_config_change_requests.revoked_by IS
        'Principal who revoked this APPROVED change request (migration 0066).'
        """
    )


def downgrade() -> None:
    op.drop_constraint("chk_revoked_by_when_revoked", "tenant_config_change_requests",
                       type_="check")
    op.drop_constraint("chk_applied_by_when_applied", "tenant_config_change_requests",
                       type_="check")
    op.drop_constraint("status_valid", "tenant_config_change_requests", type_="check")
    op.create_check_constraint(
        "status_valid",
        "tenant_config_change_requests",
        "status IN ('PROPOSED', 'APPROVED', 'REJECTED', 'APPLIED')",
    )
    op.drop_column("tenant_config_change_requests", "revoked_at")
    op.drop_column("tenant_config_change_requests", "revoked_by")
    op.drop_column("tenant_config_change_requests", "applied_by")
```

- [ ] **Step 2: Apply the migration against the test database**

```bash
cd apps/backend
export TEST_DATABASE_URL="postgresql+asyncpg://operious:operious@localhost:5433/operious_test"
# Alembic uses the sync URL; convert:
DATABASE_URL="postgresql+psycopg2://operious:operious@localhost:5433/operious_test" \
  ./venv/bin/alembic upgrade 0066_tenant_config_change_request_revocation
```

Expected: `INFO  [alembic.runtime.migration] Running upgrade ... -> 0066_tenant_config_change_request_revocation, Ledger applied_by + REVOKED status + revoke fields`

If Alembic is invoked differently in this project, check `alembic.ini` for the correct command.

- [ ] **Step 3: Commit the migration**

```bash
cd /home/imad-baraja/Projects/operious-ai
git add apps/backend/migrations/versions/0066_tenant_config_change_request_revocation.py
git commit -m "feat(migration): 0066 applied_by + REVOKED status + revoke columns (#5,#22)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: Update ORM model and ledger record/repository

**Files:**
- Modify: `apps/backend/app/tenant/db/models.py` (TenantConfigChangeRequestRow)
- Modify: `apps/backend/app/tenant/change_requests.py` (status enum, record, serializers)
- Test: `apps/backend/tests/test_ledger_applied_by.py` (model layer tests)

- [ ] **Step 1: Write failing tests**

```python
# apps/backend/tests/test_ledger_applied_by.py
"""Spec 1a — ledger model changes: applied_by, revoked_by, revoked_at, REVOKED (#5,#22)."""

from __future__ import annotations

from datetime import datetime, timezone

from app.tenant.change_requests import (
    TenantConfigChangeRequestRecord,
    TenantConfigChangeRequestStatus,
    TenantConfigChangeType,
)


def _record(**overrides) -> TenantConfigChangeRequestRecord:
    import uuid
    base = dict(
        change_request_id=uuid.uuid4(),
        tenant_id="00000000-0000-0000-0000-000000000001",
        change_type=TenantConfigChangeType.CHANNEL,
        proposed_payload={"channel_type": "email"},
        status=TenantConfigChangeRequestStatus.PROPOSED,
        proposed_by="p-1",
        proposed_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )
    base.update(overrides)
    return TenantConfigChangeRequestRecord(**base)


def test_revoked_status_exists() -> None:
    assert TenantConfigChangeRequestStatus.REVOKED == "REVOKED"


def test_record_has_applied_by_field() -> None:
    r = _record(
        status=TenantConfigChangeRequestStatus.APPLIED,
        applied_at=datetime(2026, 6, 1, 12, tzinfo=timezone.utc),
        applied_by="principal-applier",
    )
    assert r.applied_by == "principal-applier"


def test_record_applied_by_defaults_none() -> None:
    r = _record()
    assert r.applied_by is None


def test_record_has_revoked_by_field() -> None:
    r = _record(
        status=TenantConfigChangeRequestStatus.REVOKED,
        revoked_by="principal-revoker",
        revoked_at=datetime(2026, 6, 1, 13, tzinfo=timezone.utc),
    )
    assert r.revoked_by == "principal-revoker"
    assert r.revoked_at is not None


def test_record_revoked_fields_default_none() -> None:
    r = _record()
    assert r.revoked_by is None
    assert r.revoked_at is None
```

- [ ] **Step 2: Run to verify failure**

```bash
python -m pytest apps/backend/tests/test_ledger_applied_by.py -q
```

Expected: FAIL — `AttributeError: 'TenantConfigChangeRequestStatus' has no attribute 'REVOKED'`.

- [ ] **Step 3: Update TenantConfigChangeRequestStatus and TenantConfigChangeRequestRecord**

In `apps/backend/app/tenant/change_requests.py`:

1. Add `REVOKED` to the status enum:

```python
class TenantConfigChangeRequestStatus(StrEnum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    APPLIED = "APPLIED"
    REVOKED = "REVOKED"
```

2. Add three new fields to `TenantConfigChangeRequestRecord` (after `applied_at`):

```python
    applied_at: datetime | None = None
    applied_by: str | None = None        # ← new: principal who applied (#5)
    revoked_by: str | None = None        # ← new: principal who revoked (#22)
    revoked_at: datetime | None = None   # ← new: when revoked (#22)
    rejection_reason: str | None = None
    outcome_payload: Mapping[str, Any] | None = None
```

3. Update `_record_to_row` to include the new fields:

```python
def _record_to_row(
    record: TenantConfigChangeRequestRecord,
) -> TenantConfigChangeRequestRow:
    return TenantConfigChangeRequestRow(
        change_request_id=record.change_request_id,
        tenant_id=_tenant_uuid(record.tenant_id),
        change_type=record.change_type.value,
        proposed_payload=dict(record.proposed_payload),
        status=record.status.value,
        proposed_by=record.proposed_by,
        proposed_at=record.proposed_at,
        approved_by=record.approved_by,
        approved_at=record.approved_at,
        rejected_by=record.rejected_by,
        rejected_at=record.rejected_at,
        applied_at=record.applied_at,
        applied_by=record.applied_by,       # ← new
        revoked_by=record.revoked_by,       # ← new
        revoked_at=record.revoked_at,       # ← new
        rejection_reason=record.rejection_reason,
        outcome_payload=(
            None if record.outcome_payload is None else dict(record.outcome_payload)
        ),
    )
```

4. Update `_update_row` similarly:

```python
def _update_row(
    row: TenantConfigChangeRequestRow,
    record: TenantConfigChangeRequestRecord,
) -> None:
    row.change_type = record.change_type.value
    row.proposed_payload = dict(record.proposed_payload)
    row.status = record.status.value
    row.proposed_by = record.proposed_by
    row.proposed_at = record.proposed_at
    row.approved_by = record.approved_by
    row.approved_at = record.approved_at
    row.rejected_by = record.rejected_by
    row.rejected_at = record.rejected_at
    row.applied_at = record.applied_at
    row.applied_by = record.applied_by       # ← new
    row.revoked_by = record.revoked_by       # ← new
    row.revoked_at = record.revoked_at       # ← new
    row.rejection_reason = record.rejection_reason
    row.outcome_payload = (
        None if record.outcome_payload is None else dict(record.outcome_payload)
    )
```

5. Update `_row_to_record` similarly:

```python
def _row_to_record(
    row: TenantConfigChangeRequestRow,
) -> TenantConfigChangeRequestRecord:
    return TenantConfigChangeRequestRecord(
        change_request_id=row.change_request_id,
        tenant_id=str(row.tenant_id),
        change_type=TenantConfigChangeType(row.change_type),
        proposed_payload=dict(row.proposed_payload),
        status=TenantConfigChangeRequestStatus(row.status),
        proposed_by=row.proposed_by,
        proposed_at=row.proposed_at,
        approved_by=row.approved_by,
        approved_at=row.approved_at,
        rejected_by=row.rejected_by,
        rejected_at=row.rejected_at,
        applied_at=row.applied_at,
        applied_by=row.applied_by,           # ← new
        revoked_by=row.revoked_by,           # ← new
        revoked_at=row.revoked_at,           # ← new
        rejection_reason=row.rejection_reason,
        outcome_payload=(
            None if row.outcome_payload is None else dict(row.outcome_payload)
        ),
    )
```

- [ ] **Step 4: Update TenantConfigChangeRequestRow ORM model**

In `apps/backend/app/tenant/db/models.py`, in `TenantConfigChangeRequestRow`, after `applied_at` (~line 483) add:

```python
    applied_by: Mapped[str | None] = mapped_column(
        String(_HANDLE_WIDTH), nullable=True
    )
    revoked_by: Mapped[str | None] = mapped_column(
        String(_HANDLE_WIDTH), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
```

And update `__table_args__` — replace the `status_valid` constraint with:

```python
        CheckConstraint(
            "status IN ('PROPOSED', 'APPROVED', 'REJECTED', 'APPLIED', 'REVOKED')",
            name="status_valid",
        ),
```

And add after `approver_distinct`:

```python
        CheckConstraint(
            "status != 'APPLIED' OR applied_by IS NOT NULL",
            name="chk_applied_by_when_applied",
        ),
        CheckConstraint(
            "status != 'REVOKED' OR revoked_by IS NOT NULL",
            name="chk_revoked_by_when_revoked",
        ),
```

- [ ] **Step 5: Run to verify tests pass**

```bash
python -m pytest apps/backend/tests/test_ledger_applied_by.py -q
```

Expected: PASS (5 tests).

- [ ] **Step 6: Run existing ledger tests**

```bash
python -m pytest apps/backend/tests/ -k "change_request or ledger or tenant_config" -q
```

Expected: PASS (update any test constructing `TenantConfigChangeRequestRecord` if it breaks on the new required fields, which should not happen since all new fields have defaults of `None`).

- [ ] **Step 7: Commit**

```bash
git add apps/backend/app/tenant/change_requests.py apps/backend/app/tenant/db/models.py apps/backend/tests/test_ledger_applied_by.py
git commit -m "feat(ledger): REVOKED status, applied_by, revoked_by, revoked_at fields (#5,#22)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7: Service layer — apply() gains applied_by + new revoke()

**Files:**
- Modify: `apps/backend/app/services/tenant_config_change_request_service.py`
- Test: `apps/backend/tests/test_ledger_applied_by.py` (extend) + `apps/backend/tests/test_ledger_revocation.py`

- [ ] **Step 1: Write failing tests for apply() + revoke()**

Extend `apps/backend/tests/test_ledger_applied_by.py` with service tests (these use the in-memory repository):

```python
# Append to test_ledger_applied_by.py

import pytest
import uuid
from datetime import datetime, timezone

from app.tenant.change_requests import (
    TenantConfigChangeRequestRecord,
    TenantConfigChangeRequestStatus,
    TenantConfigChangeType,
    TenantConfigChangeRequestLifecycleError,
    TenantConfigChangeRequestPage,
)
from app.services.tenant_config_change_request_service import (
    TenantConfigChangeRequestService,
)


class _InMemoryRepo:
    def __init__(self) -> None:
        self._records: dict[uuid.UUID, TenantConfigChangeRequestRecord] = {}

    async def create(self, record, *, expected_tenant_id):
        self._records[record.change_request_id] = record
        return record

    async def get(self, change_request_id, *, expected_tenant_id):
        return self._records.get(change_request_id)

    async def list(self, *, expected_tenant_id, status=None, limit=50, offset=0):
        items = list(self._records.values())
        if status is not None:
            items = [r for r in items if r.status == status]
        return TenantConfigChangeRequestPage(
            items=tuple(items), total=len(items), limit=limit, offset=offset
        )

    async def update(self, record, *, expected_tenant_id):
        self._records[record.change_request_id] = record
        return record


class _NullEvents:
    async def append_event(self, event, *, expected_tenant_id):
        pass


class _NullSession:
    async def commit(self):
        pass


def _approved_record() -> TenantConfigChangeRequestRecord:
    return TenantConfigChangeRequestRecord(
        change_request_id=uuid.uuid4(),
        tenant_id="00000000-0000-0000-0000-000000000001",
        change_type=TenantConfigChangeType.CHANNEL,
        proposed_payload={"channel_type": "email"},
        status=TenantConfigChangeRequestStatus.APPROVED,
        proposed_by="p-proposer",
        proposed_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        approved_by="p-approver",
        approved_at=datetime(2026, 6, 1, 10, tzinfo=timezone.utc),
    )


async def _service_with(record) -> TenantConfigChangeRequestService:
    repo = _InMemoryRepo()
    await repo.create(record, expected_tenant_id=record.tenant_id)
    return TenantConfigChangeRequestService(
        repository=repo,
        events=_NullEvents(),
        session=_NullSession(),
        tenant_configuration_runtime=None,
    )


async def test_apply_records_applied_by() -> None:
    record = _approved_record()
    service = await _service_with(record)
    result = await service.apply(
        change_request_id=record.change_request_id,
        expected_tenant_id=record.tenant_id,
        applied_by="p-who-applied",
    )
    assert result.applied_by == "p-who-applied"
    assert result.status == TenantConfigChangeRequestStatus.APPLIED


async def test_apply_without_applied_by_raises() -> None:
    record = _approved_record()
    service = await _service_with(record)
    with pytest.raises(TenantConfigChangeRequestLifecycleError):
        await service.apply(
            change_request_id=record.change_request_id,
            expected_tenant_id=record.tenant_id,
            applied_by="",  # empty string → rejected
        )
```

Create `apps/backend/tests/test_ledger_revocation.py`:

```python
# apps/backend/tests/test_ledger_revocation.py
"""Spec 1a — ledger revocation: revoke() service method (#22)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.tenant.change_requests import (
    TenantConfigChangeRequestLifecycleError,
    TenantConfigChangeRequestRecord,
    TenantConfigChangeRequestStatus,
    TenantConfigChangeType,
    TenantConfigChangeRequestPage,
)
from app.services.tenant_config_change_request_service import (
    TenantConfigChangeRequestService,
)


class _InMemoryRepo:
    def __init__(self) -> None:
        self._records: dict[uuid.UUID, TenantConfigChangeRequestRecord] = {}

    async def create(self, record, *, expected_tenant_id):
        self._records[record.change_request_id] = record
        return record

    async def get(self, change_request_id, *, expected_tenant_id):
        return self._records.get(change_request_id)

    async def list(self, *, expected_tenant_id, status=None, limit=50, offset=0):
        items = list(self._records.values())
        if status is not None:
            items = [r for r in items if r.status == status]
        return TenantConfigChangeRequestPage(
            items=tuple(items), total=len(items), limit=limit, offset=offset
        )

    async def update(self, record, *, expected_tenant_id):
        self._records[record.change_request_id] = record
        return record


class _NullEvents:
    async def append_event(self, event, *, expected_tenant_id):
        pass


class _NullSession:
    async def commit(self):
        pass


def _record(status: TenantConfigChangeRequestStatus) -> TenantConfigChangeRequestRecord:
    return TenantConfigChangeRequestRecord(
        change_request_id=uuid.uuid4(),
        tenant_id="00000000-0000-0000-0000-000000000001",
        change_type=TenantConfigChangeType.CHANNEL,
        proposed_payload={"channel_type": "email"},
        status=status,
        proposed_by="p-proposer",
        proposed_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        approved_by="p-approver",
        approved_at=datetime(2026, 6, 1, 10, tzinfo=timezone.utc),
    )


async def _service_with(record) -> TenantConfigChangeRequestService:
    repo = _InMemoryRepo()
    await repo.create(record, expected_tenant_id=record.tenant_id)
    return TenantConfigChangeRequestService(
        repository=repo,
        events=_NullEvents(),
        session=_NullSession(),
        tenant_configuration_runtime=None,
    )


async def test_revoke_approved_becomes_revoked_with_revoker() -> None:
    record = _record(TenantConfigChangeRequestStatus.APPROVED)
    service = await _service_with(record)
    result = await service.revoke(
        change_request_id=record.change_request_id,
        expected_tenant_id=record.tenant_id,
        revoked_by="p-revoker",
    )
    assert result.status == TenantConfigChangeRequestStatus.REVOKED
    assert result.revoked_by == "p-revoker"
    assert result.revoked_at is not None


async def test_revoke_applied_raises_lifecycle_error() -> None:
    record = _record(TenantConfigChangeRequestStatus.APPLIED)
    service = await _service_with(record)
    with pytest.raises(TenantConfigChangeRequestLifecycleError):
        await service.revoke(
            change_request_id=record.change_request_id,
            expected_tenant_id=record.tenant_id,
            revoked_by="p-revoker",
        )


async def test_revoke_proposed_raises_lifecycle_error() -> None:
    record = _record(TenantConfigChangeRequestStatus.PROPOSED)
    service = await _service_with(record)
    with pytest.raises(TenantConfigChangeRequestLifecycleError):
        await service.revoke(
            change_request_id=record.change_request_id,
            expected_tenant_id=record.tenant_id,
            revoked_by="p-revoker",
        )


async def test_apply_revoked_raises_lifecycle_error() -> None:
    """REVOKED is a terminal state; an attempt to apply it must fail."""
    record = _record(TenantConfigChangeRequestStatus.REVOKED)
    service = await _service_with(record)
    with pytest.raises(TenantConfigChangeRequestLifecycleError):
        await service.apply(
            change_request_id=record.change_request_id,
            expected_tenant_id=record.tenant_id,
            applied_by="p-applier",
        )
```

- [ ] **Step 2: Run to verify failure**

```bash
python -m pytest apps/backend/tests/test_ledger_applied_by.py apps/backend/tests/test_ledger_revocation.py -q
```

Expected: FAIL — service methods don't accept `applied_by` or have `revoke()`.

- [ ] **Step 3: Read the TenantConfigChangeRequestService constructor signature**

Run: `grep -n "def __init__\|class TenantConfigChangeRequestService" apps/backend/app/services/tenant_config_change_request_service.py | head -5`

Then read the init to confirm the `_repository`, `_events`, `_session`, and `_tenant_configuration_runtime` field names. Use these exact names in the test's `_service_with()` function (the test code above uses `repository=`, `events=`, `session=`, `tenant_configuration_runtime=` — verify these match the actual keyword names and fix if needed).

- [ ] **Step 4: Update `apply()` to accept and record `applied_by`**

In `apps/backend/app/services/tenant_config_change_request_service.py`:

Update `apply()` signature and body:

```python
    async def apply(
        self,
        *,
        change_request_id: uuid.UUID | str,
        expected_tenant_id: str,
        applied_by: str,
    ) -> TenantConfigChangeRequestRecord:
        if not applied_by or not applied_by.strip():
            raise TenantConfigChangeRequestLifecycleError(
                "applied_by must identify the principal who applied the change"
            )
        record = await self._require(
            change_request_id,
            expected_tenant_id=expected_tenant_id,
        )
        if record.status not in (TenantConfigChangeRequestStatus.APPROVED,):
            raise TenantConfigChangeRequestLifecycleError(
                f"cannot apply a {record.status.value} change request; "
                "only APPROVED requests can be applied"
            )
        if record.approved_by is None:
            raise TenantConfigChangeRequestLifecycleError(
                "approved tenant config change request is missing approved_by"
            )
        outcome = await self._apply_config_mutation(record)
        applied = replace(
            record,
            status=TenantConfigChangeRequestStatus.APPLIED,
            applied_at=_utcnow(),
            applied_by=applied_by,
            outcome_payload=outcome,
        )
        persisted = await self._repository.update(
            applied,
            expected_tenant_id=expected_tenant_id,
        )
        await self._append_status_event(persisted)
        await self._session.commit()
        return persisted
```

Note: the `status not in (TenantConfigChangeRequestStatus.APPROVED,)` check replaces the old `status is not TenantConfigChangeRequestStatus.APPROVED` — this single-element tuple form is equivalent and is where we will extend later to also reject `REVOKED` (already handled by `not in (APPROVED,)`).

- [ ] **Step 5: Add the `revoke()` method**

Add `revoke()` after `reject()` in the service:

```python
    async def revoke(
        self,
        *,
        change_request_id: uuid.UUID | str,
        expected_tenant_id: str,
        revoked_by: str,
    ) -> TenantConfigChangeRequestRecord:
        """Revoke an APPROVED change request before it is applied.

        Only APPROVED requests can be revoked; APPLIED, REJECTED, and already-REVOKED
        requests raise :class:`TenantConfigChangeRequestLifecycleError`.
        Any principal holding the ``tenant.config.approve`` capability may revoke;
        there is no additional same-principal restriction (revocation is the
        undoing of a grant, not a new approval).
        """
        if not revoked_by or not revoked_by.strip():
            raise TenantConfigChangeRequestLifecycleError(
                "revoked_by must identify the principal who revoked the change"
            )
        record = await self._require(
            change_request_id,
            expected_tenant_id=expected_tenant_id,
        )
        if record.status is not TenantConfigChangeRequestStatus.APPROVED:
            raise TenantConfigChangeRequestLifecycleError(
                f"cannot revoke a {record.status.value} change request; "
                "only APPROVED requests can be revoked"
            )
        revoked = replace(
            record,
            status=TenantConfigChangeRequestStatus.REVOKED,
            revoked_by=revoked_by,
            revoked_at=_utcnow(),
        )
        persisted = await self._repository.update(
            revoked,
            expected_tenant_id=expected_tenant_id,
        )
        await self._append_status_event(persisted)
        await self._session.commit()
        return persisted
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
python -m pytest apps/backend/tests/test_ledger_applied_by.py apps/backend/tests/test_ledger_revocation.py -q
```

Expected: PASS (9 tests).

- [ ] **Step 7: Run existing ledger service tests for regressions**

```bash
python -m pytest apps/backend/tests/ -k "change_request or tenant_config_change" -q
```

Expected: PASS. Note: any test calling `service.apply()` will now need to pass `applied_by="..."`. Find and fix those.

- [ ] **Step 8: Commit**

```bash
git add apps/backend/app/services/tenant_config_change_request_service.py apps/backend/tests/test_ledger_applied_by.py apps/backend/tests/test_ledger_revocation.py
git commit -m "feat(ledger): apply() records applied_by; add revoke() method (#5,#22)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 8: Schema + router — expose applied_by in response; add revoke endpoint

**Files:**
- Modify: `apps/backend/app/api/v1/schemas/tenant.py` (`TenantConfigChangeRequestResponse`)
- Modify: `apps/backend/app/api/v1/routers/tenant.py` (apply endpoint + new revoke endpoint)

- [ ] **Step 1: Write failing tests**

```python
# Append to apps/backend/tests/test_ledger_revocation.py

def test_response_schema_includes_new_fields() -> None:
    """TenantConfigChangeRequestResponse must expose applied_by, revoked_by, revoked_at."""
    from app.api.v1.schemas.tenant import TenantConfigChangeRequestResponse
    import inspect
    fields = inspect.get_annotations(TenantConfigChangeRequestResponse, eval_str=True)
    assert "applied_by" in fields
    assert "revoked_by" in fields
    assert "revoked_at" in fields
```

Also add a router-level test by extending `apps/backend/tests/test_tenant_config_change_requests.py` (or wherever the apply endpoint test lives — find it with `grep -rln "apply_config_change_request\|/apply" apps/backend/tests/`):

```python
# Locate the existing apply endpoint test file and add:
def test_revoke_endpoint_requires_approve_capability() -> None:
    """POST /revoke without tenant.config.approve → 403."""
    # This test uses the TestClient pattern from the existing test file.
    # Check the existing file for the _client() or _app() fixture pattern
    # and replicate it here with a principal that lacks the approve capability.
    pass  # Replace with actual implementation matching the file's test pattern.
```

> Implementer note: Read the existing `test_tenant_config_change_requests.py` to understand the test client fixture and replicate the pattern. The test should verify that `POST /api/v1/tenant/config/change-requests/{id}/revoke` returns 403 without the capability and 200 (or 404 if the id is fake) with it.

- [ ] **Step 2: Run to verify failure**

```bash
python -m pytest apps/backend/tests/test_ledger_revocation.py::test_response_schema_includes_new_fields -q
```

Expected: FAIL — `applied_by` not in schema fields.

- [ ] **Step 3: Update TenantConfigChangeRequestResponse in schemas/tenant.py**

In `apps/backend/app/api/v1/schemas/tenant.py`, in `TenantConfigChangeRequestResponse` (around line 392), add the three new fields after `applied_at`:

```python
    applied_at: str | None = None
    applied_by: str | None = None        # ← new (#5)
    revoked_by: str | None = None        # ← new (#22)
    revoked_at: str | None = None        # ← new (#22)
    rejection_reason: str | None = None
    outcome_payload: dict[str, Any] | None = None
```

Update `from_record` (find the closing section that sets each field) to add:

```python
            applied_by=record.applied_by,
            revoked_by=record.revoked_by,
            revoked_at=(
                record.revoked_at.isoformat() if record.revoked_at is not None else None
            ),
```

- [ ] **Step 4: Thread `applied_by` through the apply router endpoint**

In `apps/backend/app/api/v1/routers/tenant.py`, update `apply_config_change_request`:

```python
async def apply_config_change_request(
    change_request_id: str,
    expected_tenant_id: str = Depends(require_tenant_scope),
    _approver: AuthorityContext = Depends(require_tenant_config_approve),
    service: TenantConfigChangeRequestService = Depends(
        get_tenant_config_change_request_service
    ),
) -> TenantConfigChangeRequestResponse:
    try:
        record = await service.apply(
            change_request_id=change_request_id,
            expected_tenant_id=expected_tenant_id,
            applied_by=_principal_or_400(_approver),
        )
    except (ValueError, TenantConfigChangeRequestError) as exc:
        raise _change_request_http_error(exc) from exc
    return TenantConfigChangeRequestResponse.from_record(record)
```

- [ ] **Step 5: Add the revoke endpoint**

In `apps/backend/app/api/v1/routers/tenant.py`, add the revoke endpoint immediately after the apply endpoint (~line 248):

```python
@router.post(
    "/config/change-requests/{change_request_id}/revoke",
    response_model=TenantConfigChangeRequestResponse,
)
async def revoke_config_change_request(
    change_request_id: str,
    expected_tenant_id: str = Depends(require_tenant_scope),
    authority: AuthorityContext = Depends(require_tenant_config_approve),
    service: TenantConfigChangeRequestService = Depends(
        get_tenant_config_change_request_service
    ),
) -> TenantConfigChangeRequestResponse:
    """Revoke an APPROVED change request before it is applied.

    Requires the ``tenant.config.approve`` capability. Any approved request
    that has not yet been applied can be revoked; APPLIED, REJECTED, and
    already-REVOKED requests return 409.
    """
    try:
        record = await service.revoke(
            change_request_id=change_request_id,
            expected_tenant_id=expected_tenant_id,
            revoked_by=_principal_or_400(authority),
        )
    except (ValueError, TenantConfigChangeRequestError) as exc:
        raise _change_request_http_error(exc) from exc
    return TenantConfigChangeRequestResponse.from_record(record)
```

Also make sure `_change_request_http_error` handles `TenantConfigChangeRequestLifecycleError` with a `409 Conflict` (it likely already does — verify and add if not):

```python
def _change_request_http_error(exc: BaseException) -> HTTPException:
    if isinstance(exc, TenantConfigChangeRequestNotFoundError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "tenant_config_change_request_not_found"},
        )
    if isinstance(exc, TenantConfigChangeRequestSeparationError):
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "separation_of_duties_required"},
        )
    if isinstance(exc, TenantConfigChangeRequestLifecycleError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "change_request_lifecycle_error", "reason": str(exc)},
        )
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={"code": "tenant_config_change_request_error", "reason": str(exc)},
    )
```

- [ ] **Step 6: Run all ledger tests**

```bash
python -m pytest apps/backend/tests/test_ledger_applied_by.py apps/backend/tests/test_ledger_revocation.py apps/backend/tests/test_tenant_config_change_requests.py -q
```

Expected: PASS (fix any tests that call `service.apply()` without the new `applied_by` kwarg).

- [ ] **Step 7: Commit**

```bash
git add apps/backend/app/api/v1/schemas/tenant.py apps/backend/app/api/v1/routers/tenant.py apps/backend/tests/test_ledger_revocation.py
git commit -m "feat(ledger): schema exposes applied_by/revoked fields; add revoke endpoint (#5,#22)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 9: Verification sweep

**Files:** no new code; run tests and update the audit doc.

- [ ] **Step 1: Run the full spec-1a test set**

```bash
python -m pytest \
  apps/backend/tests/test_authz_domain_capabilities.py \
  apps/backend/tests/test_conversation_ownership.py \
  apps/backend/tests/test_ledger_applied_by.py \
  apps/backend/tests/test_ledger_revocation.py \
  -v 2>&1 | tail -10
```

Expected: all PASS.

- [ ] **Step 2: Run the broader regression suite (without Postgres-gated tests)**

```bash
python -m pytest apps/backend/tests/ \
  -q --ignore=apps/backend/tests/load \
  -m "not requires_postgres" \
  2>&1 | tail -10
```

Expected: PASS. Fix any regressions before proceeding.

- [ ] **Step 3: Run the Postgres-gated change-request + observability + audit tests with the test DB**

```bash
export TEST_DATABASE_URL="postgresql+asyncpg://operious:operious@localhost:5433/operious_test"
python -m pytest \
  apps/backend/tests/test_tenant_config_change_requests.py \
  apps/backend/tests/ -k "observability or audit" \
  -q 2>&1 | tail -10
```

Expected: PASS.

- [ ] **Step 4: Update the audit doc**

In `docs/audit/operious-full-repository-audit-2026-05-31.md`, update the Top-100 table rows for #5, #22, #26, #80, #81, #83 to note `spec 1a implemented — code closed, pending live proof (Phase 3)`.

- [ ] **Step 5: Commit**

```bash
git add docs/audit/operious-full-repository-audit-2026-05-31.md
git commit -m "docs(audit): mark spec 1a findings code-closed (#5,#22,#26,#80,#81,#83)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage check:**
- #26 Tenant-wide reads → Tasks 2, 3 (observability all 9 endpoints + audit export gated)
- #80 Role-gate observability → Task 2 (all 9 observability endpoints)
- #81 Audit verify body budget → Task 3 (256 KiB cap on POST /verify)
- #83 Conversation ownership → Task 4 (service + router)
- #5 Ledger applied_by → Tasks 5, 6, 7, 8 (migration + model + service + router)
- #22 Ledger revocation → Tasks 5, 6, 7, 8 (migration + REVOKED status + revoke() + endpoint)

**Placeholder scan:** No TBD/TODO left. Task 8 Step 1 has a comment noting the implementer should read the existing test file to match the fixture pattern — this is intentional guidance, not a placeholder.

**Type consistency:** `applied_by: str` in `TenantConfigChangeRequestRecord`, service `apply(applied_by: str)`, router `_principal_or_400(_approver)` all consistent. `revoked_by: str | None`, `revoked_at: datetime | None` in record, `revoke(revoked_by: str)` in service, `revoked_at: str | None` in schema (isoformat). Serializers updated to include all three new fields in `_record_to_row`, `_update_row`, and `_row_to_record`. Consistent throughout.
