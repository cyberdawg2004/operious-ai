"""Spec 1a: domain capability constants, dependency functions, and Auth0 mapping."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from starlette.requests import Request
from starlette.testclient import TestClient

from app.auth.providers.jwt import PERMISSION_CAPABILITY_MAP, ROLE_CAPABILITY_MAP
from app.dependencies.authority import (
    OPERATOR_CAPABILITY,
    TENANT_ACTIONS_APPROVE_CAPABILITY,
    TENANT_AUDIT_EXPORT_CAPABILITY,
    TENANT_COGNITION_READ_CAPABILITY,
    TENANT_CONNECTOR_APPROVE_CAPABILITY,
    TENANT_CONNECTOR_READ_CAPABILITY,
    TENANT_GOVERNANCE_READ_CAPABILITY,
    TENANT_OBSERVABILITY_READ_CAPABILITY,
    TENANT_OPERATIONS_READ_CAPABILITY,
    TENANT_PRIVACY_ADMIN_CAPABILITY,
    TENANT_PRIVACY_APPROVE_CAPABILITY,
    TENANT_SUPERVISOR_READ_CAPABILITY,
    TENANT_TRAINING_WRITE_CAPABILITY,
    require_tenant_actions_approve,
    require_tenant_audit_export,
    require_tenant_cognition_read,
    require_tenant_connector_read,
    require_tenant_governance_read,
    require_tenant_observability_read,
    require_tenant_operations_read,
    require_tenant_privacy_admin,
    require_tenant_privacy_approve,
    require_tenant_supervisor_read,
    require_tenant_training_write,
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
    assert TENANT_OPERATIONS_READ_CAPABILITY == "tenant.operations.read"
    assert TENANT_SUPERVISOR_READ_CAPABILITY == "tenant.supervisor.read"
    assert TENANT_GOVERNANCE_READ_CAPABILITY == "tenant.governance.read"
    assert TENANT_COGNITION_READ_CAPABILITY == "tenant.cognition.read"
    assert TENANT_CONNECTOR_READ_CAPABILITY == "tenant.connector.read"
    assert TENANT_CONNECTOR_APPROVE_CAPABILITY == "tenant.connector.approve"
    assert TENANT_ACTIONS_APPROVE_CAPABILITY == "tenant.actions.approve"
    assert TENANT_TRAINING_WRITE_CAPABILITY == "tenant.training.write"
    assert TENANT_PRIVACY_ADMIN_CAPABILITY == "tenant.privacy.admin"
    assert TENANT_PRIVACY_APPROVE_CAPABILITY == "tenant.privacy.approve"


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


@pytest.mark.parametrize(
    ("capability", "dependency"),
    [
        (TENANT_OPERATIONS_READ_CAPABILITY, require_tenant_operations_read),
        (TENANT_SUPERVISOR_READ_CAPABILITY, require_tenant_supervisor_read),
        (TENANT_GOVERNANCE_READ_CAPABILITY, require_tenant_governance_read),
        (TENANT_COGNITION_READ_CAPABILITY, require_tenant_cognition_read),
        (TENANT_CONNECTOR_READ_CAPABILITY, require_tenant_connector_read),
        (TENANT_ACTIONS_APPROVE_CAPABILITY, require_tenant_actions_approve),
        (TENANT_TRAINING_WRITE_CAPABILITY, require_tenant_training_write),
        (TENANT_PRIVACY_ADMIN_CAPABILITY, require_tenant_privacy_admin),
        (TENANT_PRIVACY_APPROVE_CAPABILITY, require_tenant_privacy_approve),
    ],
)
def test_1aext_capability_deps(capability: str, dependency) -> None:  # noqa: ANN001
    assert dependency(_request([capability])).tenant_id == "t-1"
    with pytest.raises(HTTPException) as exc:
        dependency(_request(["tenant_read"]))
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


def test_role_map_operator_bundle_excludes_sod_capabilities() -> None:
    assert ROLE_CAPABILITY_MAP.get("Operator") == (
        "operator",
        "tenant.operations.read",
        "tenant.supervisor.read",
        "tenant.observability.read",
    )
    operator_caps = set(ROLE_CAPABILITY_MAP["Operator"])
    assert "tenant.governance.read" not in operator_caps
    assert "tenant.cognition.read" not in operator_caps
    assert "tenant.connector.read" not in operator_caps
    assert "tenant.config.read" not in operator_caps
    assert "tenant.actions.approve" not in operator_caps
    assert "tenant.training.write" not in operator_caps
    assert "tenant.privacy.admin" not in operator_caps
    assert "tenant.privacy.approve" not in operator_caps


@pytest.mark.parametrize(
    ("role", "capability"),
    [
        ("TenantOperationsViewer", "tenant.operations.read"),
        ("TenantSupervisor", "tenant.supervisor.read"),
        ("TenantGovernanceViewer", "tenant.governance.read"),
        ("TenantCognitionViewer", "tenant.cognition.read"),
        ("TenantConnectorViewer", "tenant.connector.read"),
        ("TenantConnectorApprover", ("tenant.connector.read", "tenant.connector.approve")),
        ("TenantActionApprover", "tenant.actions.approve"),
        ("TenantTrainingWriter", "tenant.training.write"),
        ("TenantPrivacyAdmin", "tenant.privacy.admin"),
        ("TenantPrivacyApprover", "tenant.privacy.approve"),
    ],
)
def test_role_map_1aext_roles(role: str, capability: str) -> None:
    assert ROLE_CAPABILITY_MAP.get(role) == capability


def test_permission_map_observability() -> None:
    assert PERMISSION_CAPABILITY_MAP.get("read:tenant_observability") == "tenant.observability.read"


def test_permission_map_audit() -> None:
    assert PERMISSION_CAPABILITY_MAP.get("read:tenant_audit") == "tenant.audit.export"


@pytest.mark.parametrize(
    ("permission", "capability"),
    [
        ("read:tenant_operations", "tenant.operations.read"),
        ("read:tenant_supervisor", "tenant.supervisor.read"),
        ("read:tenant_governance", "tenant.governance.read"),
        ("read:tenant_cognition", "tenant.cognition.read"),
        ("read:tenant_connector", "tenant.connector.read"),
        ("read:tenant_config", "tenant.config.read"),
        ("approve:tenant_connector", ("tenant.connector.read", "tenant.connector.approve")),
        ("approve:tenant_actions", "tenant.actions.approve"),
        ("write:tenant_training", "tenant.training.write"),
        ("admin:tenant_privacy", "tenant.privacy.admin"),
        ("approve:tenant_privacy", "tenant.privacy.approve"),
    ],
)
def test_permission_map_1aext_permissions(
    permission: str,
    capability: str,
) -> None:
    assert PERMISSION_CAPABILITY_MAP.get(permission) == capability


def test_connector_writer_role_and_permission_include_read() -> None:
    assert ROLE_CAPABILITY_MAP.get("TenantConnectorWriter") == (
        "tenant.connector.write",
        "tenant.connector.read",
        "tenant.config.read",
    )
    assert PERMISSION_CAPABILITY_MAP.get("write:tenant_connector") == (
        "tenant.connector.write",
        "tenant.connector.read",
        "tenant.config.read",
    )


# ── Structural: observability router uses the capability dep on all endpoints ─

def _dep_names(route) -> list[str]:  # noqa: ANN001
    """Collect all FastAPI dependency function names on a route."""
    names = []
    for dep in getattr(route, "dependencies", []):
        if hasattr(dep.dependency, "__name__"):
            names.append(dep.dependency.__name__)
    # Also walk the endpoint function's Depends parameters.
    import inspect
    from fastapi import params as fa_params
    sig = inspect.signature(route.endpoint)
    for param in sig.parameters.values():
        if isinstance(param.default, fa_params.Depends):
            fn = param.default.dependency
            if hasattr(fn, "__name__"):
                names.append(fn.__name__)
    return names


def _observability_routes():  # noqa: ANN201
    from app.api.v1.routers.observability import router as obs_router
    return [r for r in obs_router.routes if hasattr(r, "endpoint")]


def test_all_observability_endpoints_have_capability_dep() -> None:
    """Every observability route must declare an observability capability gate.

    Write endpoints (POST /slo-definitions, POST /traces) use the write
    capability (F14); read endpoints use the read capability. Either is
    sufficient to count as gated.
    """
    _OBSERVABILITY_CAPS = {
        "require_tenant_observability_read",
        "require_tenant_observability_write",
    }
    routes = _observability_routes()
    assert len(routes) >= 9, f"Expected ≥9 routes, got {len(routes)}"
    missing = []
    for route in routes:
        deps = set(_dep_names(route))
        if not (deps & _OBSERVABILITY_CAPS):
            missing.append(getattr(route, "path", str(route)))
    assert not missing, f"Routes missing capability dep: {missing}"


def test_observability_dep_present_on_metrics_dlq_alerts_traces() -> None:
    """Spot-check four representative endpoints by path."""
    _CAPS = {"require_tenant_observability_read", "require_tenant_observability_write"}
    routes_by_path = {
        getattr(r, "path", ""): r for r in _observability_routes()
    }
    for path in ("/metrics", "/dlq", "/alerts", "/traces"):
        route = routes_by_path.get(path)
        assert route is not None, f"Route {path!r} not found"
        deps = set(_dep_names(route))
        assert deps & _CAPS, f"{path} missing observability cap dep, has: {deps}"


# ── Structural: audit export endpoint requires capability dep ─────────────────

def test_audit_export_endpoint_has_capability_dep() -> None:
    from app.api.v1.routers.audit_export import router as audit_router
    export_routes = [
        r for r in audit_router.routes
        if getattr(r, "path", "") == "/export"
    ]
    assert export_routes, "GET /export route not found"
    deps = set(_dep_names(export_routes[0]))
    assert "require_tenant_audit_export" in deps, (
        f"GET /export missing require_tenant_audit_export. Has: {deps}"
    )


# ── Body cap: POST /audit/verify rejects > 256 KiB ───────────────────────────

def test_audit_verify_body_cap_rejects_large_body() -> None:
    import json
    import os
    from unittest.mock import patch
    from app.core.config import get_settings
    from app.main import create_app

    get_settings.cache_clear()
    try:
        with patch.dict(os.environ, {
            "ENVIRONMENT": "test",
            "RATE_LIMIT_ENABLED": "false",
            "AUDIT_EXPORT_HMAC_SECRET": "s" * 32,
        }):
            app = create_app()
    finally:
        get_settings.cache_clear()

    # Build a body just over 256 KiB.
    large_export = {"signature": "x", "payload": "y" * (260 * 1024)}
    body = json.dumps({"export": large_export}).encode()
    assert len(body) > 256 * 1024

    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.post(
            "/api/v1/audit/verify",
            content=body,
            headers={"content-type": "application/json"},
        )
    assert resp.status_code == 413
