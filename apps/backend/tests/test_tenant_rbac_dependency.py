"""RBAC capability dependency for tenant configuration writes (S-02/B4).

Tenant configuration mutations (channels, knowledge, governance
policy, execution governance, topology) must require an explicit
domain capability — not merely a tenant scope. A tenant-scoped user
without the domain capability must be rejected with 403.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.dependencies.authority import (
    ERROR_CODE_AUTHORITY_REQUIRED,
    ERROR_CODE_CAPABILITY_REQUIRED,
    TENANT_ADMIN_CAPABILITY,
    TENANT_POLICY_WRITE_CAPABILITY,
    require_capability,
    require_tenant_admin,
)
from app.identity.authority import AuthorityContext
from app.identity.primitives import TenantId


def _request(authority: AuthorityContext | None = None) -> Request:
    req = Request(
        scope={
            "type": "http",
            "method": "POST",
            "headers": [],
            "path": "/test",
            "raw_path": b"/test",
            "query_string": b"",
            "state": {},
        }
    )
    if authority is not None:
        req.state.authority = authority
    return req


def test_require_capability_returns_authority_when_held() -> None:
    authority = AuthorityContext(
        tenant_id=TenantId("acme"),
        capabilities=frozenset({TENANT_POLICY_WRITE_CAPABILITY}),
    )
    dep = require_capability(TENANT_POLICY_WRITE_CAPABILITY)
    assert dep(_request(authority)) is authority


def test_require_capability_rejects_missing_capability() -> None:
    authority = AuthorityContext(
        tenant_id=TenantId("acme"),
        capabilities=frozenset({"session:open"}),
    )
    dep = require_capability(TENANT_POLICY_WRITE_CAPABILITY)
    with pytest.raises(HTTPException) as exc:
        dep(_request(authority))
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == ERROR_CODE_CAPABILITY_REQUIRED
    assert exc.value.detail["capability"] == TENANT_POLICY_WRITE_CAPABILITY


def test_require_capability_rejects_anonymous() -> None:
    dep = require_capability(TENANT_POLICY_WRITE_CAPABILITY)
    with pytest.raises(HTTPException) as exc:
        dep(_request(AuthorityContext()))
    assert exc.value.status_code == 401
    assert exc.value.detail["code"] == ERROR_CODE_AUTHORITY_REQUIRED


def test_legacy_require_tenant_admin_enforces_tenant_admin_capability() -> None:
    held = AuthorityContext(
        tenant_id=TenantId("acme"),
        capabilities=frozenset({TENANT_ADMIN_CAPABILITY}),
    )
    assert require_tenant_admin(_request(held)) is held

    missing = AuthorityContext(tenant_id=TenantId("acme"))
    with pytest.raises(HTTPException) as exc:
        require_tenant_admin(_request(missing))
    assert exc.value.status_code == 403
