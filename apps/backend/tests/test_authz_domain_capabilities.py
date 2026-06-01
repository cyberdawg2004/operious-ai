"""Spec 1a: domain capability constants, dependency functions, and Auth0 mapping."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from starlette.datastructures import Headers
from starlette.requests import Request

from app.auth.providers.jwt import PERMISSION_CAPABILITY_MAP, ROLE_CAPABILITY_MAP
from app.dependencies.authority import (
    OPERATOR_CAPABILITY,
    TENANT_AUDIT_EXPORT_CAPABILITY,
    TENANT_OBSERVABILITY_READ_CAPABILITY,
    require_tenant_audit_export,
    require_tenant_observability_read,
)
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


def test_operator_capability_does_not_bypass_domain_gate() -> None:
    # The domain gates are capability-based, not role-based.
    # Operators are expected to also hold the explicit domain capability in Auth0.
    req = _request([OPERATOR_CAPABILITY])
    with pytest.raises(HTTPException) as exc:
        require_tenant_observability_read(req)
    assert exc.value.status_code == 403


def test_role_map_tenant_observer() -> None:
    assert ROLE_CAPABILITY_MAP.get("TenantObserver") == "tenant.observability.read"


def test_role_map_tenant_auditor() -> None:
    assert ROLE_CAPABILITY_MAP.get("TenantAuditor") == "tenant.audit.export"


def test_permission_map_observability() -> None:
    assert PERMISSION_CAPABILITY_MAP.get("read:tenant_observability") == "tenant.observability.read"


def test_permission_map_audit() -> None:
    assert PERMISSION_CAPABILITY_MAP.get("read:tenant_audit") == "tenant.audit.export"
