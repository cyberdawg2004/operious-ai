"""Composition-root tenant-scope dependency contract.

Pins the behaviour of ``app.dependencies.authority`` against
the constitutional contract established by Wedge 2.75-ε:

* :func:`require_tenant_scope` rejects anonymous and tenant-less
  authorities. This is the wedge that future tenant-scoped read
  handlers transitively depend on.
* :func:`require_authority` rejects anonymous and verified
  principals that carry neither tenant scope nor platform-admin
  capability.
* :func:`request_tenant_scope_opt` returns ``None`` for both
  anonymous and tenant-less authorities — admin / internal use
  only.
* :func:`request_authority_opt` returns the bound authority or
  ``None`` without raising.

The constitutional guarantees these tests preserve:

* Anonymous → 401 with ``authority_required``.
* Bound but tenant-less → 400 with ``tenant_axis_missing``.
* Bound with tenant → string ``tenant_id`` ready to forward
  verbatim into persistence ``expected_tenant_id``.
"""

from __future__ import annotations


import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.dependencies.authority import (
    ERROR_CODE_AUTHORITY_REQUIRED,
    ERROR_CODE_AUTHORIZED_SCOPE_REQUIRED,
    ERROR_CODE_OPERATOR_AUTHORITY_REQUIRED,
    ERROR_CODE_TENANT_AXIS_MISSING,
    OPERATOR_CAPABILITY,
    PLATFORM_TENANT_ADMIN_CAPABILITY,
    request_authority_opt,
    request_tenant_scope_opt,
    require_authority,
    require_operator_authority,
    require_platform_tenant_admin,
    require_tenant_scope,
)
from app.identity.authority import AuthorityContext
from app.identity.primitives import TenantId


def _request(
    authority: AuthorityContext | None = None,
    *,
    source: str | None = None,
) -> Request:
    """Lightweight Request stand-in with a stateful ``.state``.

    Starlette's :class:`Request` exposes ``request.state`` as a
    plain attribute namespace; we mimic that contract here without
    spinning up a full ASGI scope.
    """
    req = Request(
        scope={
            "type": "http",
            "method": "GET",
            "headers": [],
            "path": "/test",
            "raw_path": b"/test",
            "query_string": b"",
            "state": {},
        }
    )
    if authority is not None:
        req.state.authority = authority
    if source is not None:
        req.state.authority_source = source
    return req


# ─── require_authority ──────────────────────────────────────────────


def test_require_authority_returns_bound_authority() -> None:
    authority = AuthorityContext(tenant_id=TenantId("acme"))
    assert require_authority(_request(authority)) is authority


def test_require_authority_allows_verified_platform_admin_without_tenant() -> (
    None
):
    from app.identity.primitives import PrincipalId

    authority = AuthorityContext(
        principal_id=PrincipalId("platform-admin"),
        capabilities=frozenset({PLATFORM_TENANT_ADMIN_CAPABILITY}),
    )
    assert (
        require_authority(_request(authority, source="verified"))
        is authority
    )


def test_require_authority_allows_header_attested_principal_without_tenant() -> (
    None
):
    from app.identity.primitives import PrincipalId

    authority = AuthorityContext(
        principal_id=PrincipalId("header-principal")
    )
    assert (
        require_authority(_request(authority, source="header"))
        is authority
    )


def test_require_authority_raises_401_when_anonymous() -> None:
    with pytest.raises(HTTPException) as excinfo:
        require_authority(_request(None))
    assert excinfo.value.status_code == 401
    assert excinfo.value.detail == {
        "code": ERROR_CODE_AUTHORITY_REQUIRED
    }
    assert (
        excinfo.value.headers is not None
        and excinfo.value.headers.get("WWW-Authenticate") == "Bearer"
    )


def test_require_authority_raises_403_when_verified_scope_missing() -> (
    None
):
    """A verified bearer without tenant scope or platform-admin
    authority is authenticated but unusable, so app entry fails
    closed before any route runs."""
    from app.identity.primitives import PrincipalId

    authority = AuthorityContext(
        principal_id=PrincipalId("user-1")
    )
    with pytest.raises(HTTPException) as excinfo:
        require_authority(_request(authority, source="verified"))
    assert excinfo.value.status_code == 403
    assert excinfo.value.detail == {
        "code": ERROR_CODE_AUTHORIZED_SCOPE_REQUIRED
    }


def test_require_authority_raises_401_when_bound_but_fully_anonymous() -> None:
    """PR-D1 contract — match the docstring's "rejects anonymous"
    promise against the middleware's bound-empty state.

    :class:`AuthorityContextMiddleware` binds an empty
    :class:`AuthorityContext` to every anonymous ingress (no
    Authorization, no X-*-ID headers). The pre-PR-D1 dependency
    only rejected the ``state.authority is None`` state, which is
    a test-only stand-in — production requests always have the
    middleware-bound empty context. Tightening the check closes
    the gap so anonymous production requests get the same 401
    the docstring already promised.
    """
    empty = AuthorityContext()
    assert empty.is_fully_anonymous is True
    with pytest.raises(HTTPException) as excinfo:
        require_authority(_request(empty))
    assert excinfo.value.status_code == 401
    assert excinfo.value.detail == {
        "code": ERROR_CODE_AUTHORITY_REQUIRED
    }
    assert (
        excinfo.value.headers is not None
        and excinfo.value.headers.get("WWW-Authenticate") == "Bearer"
    )


# ─── require_tenant_scope ───────────────────────────────────────────


def test_require_tenant_scope_returns_string_tenant() -> None:
    authority = AuthorityContext(tenant_id=TenantId("acme"))
    scope = require_tenant_scope(_request(authority))
    assert scope == "acme"
    assert isinstance(scope, str)


def test_require_tenant_scope_raises_401_when_anonymous() -> None:
    with pytest.raises(HTTPException) as excinfo:
        require_tenant_scope(_request(None))
    assert excinfo.value.status_code == 401
    assert excinfo.value.detail == {
        "code": ERROR_CODE_AUTHORITY_REQUIRED
    }


def test_require_tenant_scope_raises_400_when_tenant_axis_missing() -> (
    None
):
    """An authenticated authority WITHOUT a tenant axis still
    cannot enumerate tenant-scoped resources. Returning ALL
    tenants' records would breach the multi-tenant boundary;
    returning NONE silently would mask the upstream
    misconfiguration. The platform refuses with 400.

    PR-D1 note: the fixture must populate AT LEAST one axis so
    the authority is not :attr:`is_fully_anonymous` — otherwise
    :func:`require_authority` (which ``require_tenant_scope``
    calls first) would short-circuit with 401 before the tenant
    check runs. Using ``principal_id`` here pins the "verified
    principal, but token has no tenant claim" state precisely.
    """
    from app.identity.primitives import PrincipalId

    authority = AuthorityContext(principal_id=PrincipalId("user-1"))
    with pytest.raises(HTTPException) as excinfo:
        require_tenant_scope(_request(authority))
    assert excinfo.value.status_code == 400
    assert excinfo.value.detail == {
        "code": ERROR_CODE_TENANT_AXIS_MISSING
    }


# ─── request_authority_opt ──────────────────────────────────────────


def test_request_authority_opt_returns_authority_when_bound() -> None:
    authority = AuthorityContext(tenant_id=TenantId("acme"))
    assert request_authority_opt(_request(authority)) is authority


def test_request_authority_opt_returns_none_when_anonymous() -> None:
    assert request_authority_opt(_request(None)) is None


# ─── request_tenant_scope_opt ───────────────────────────────────────


def test_request_tenant_scope_opt_returns_tenant_when_present() -> None:
    authority = AuthorityContext(tenant_id=TenantId("acme"))
    assert request_tenant_scope_opt(_request(authority)) == "acme"


def test_request_tenant_scope_opt_returns_none_when_anonymous() -> None:
    assert request_tenant_scope_opt(_request(None)) is None


def test_request_tenant_scope_opt_returns_none_when_tenant_missing() -> (
    None
):
    """Tenant-less authority still yields ``None`` — admin
    handlers using this dependency are unconstrained.

    The fixture populates ``principal_id`` so the test
    distinguishes "authenticated principal with no tenant axis"
    from "fully anonymous" (the latter is covered by
    ``test_request_tenant_scope_opt_returns_none_when_anonymous``
    above)."""
    from app.identity.primitives import PrincipalId

    authority = AuthorityContext(principal_id=PrincipalId("user-1"))
    assert request_tenant_scope_opt(_request(authority)) is None


# ─── Composition-root contract ──────────────────────────────────────


def test_module_exports_stable_contract() -> None:
    """The public surface of ``app.dependencies.authority`` is
    constitutionally pinned — adding / removing helpers requires
    explicit doctrine review. Reviewers MUST update this list
    AND the docstring before any merge that mutates the public
    surface."""
    from app.dependencies import authority as mod

    assert sorted(mod.__all__) == [
        "ERROR_CODE_AUTHORITY_REQUIRED",
        "ERROR_CODE_AUTHORIZED_SCOPE_REQUIRED",
        "ERROR_CODE_CAPABILITY_REQUIRED",
        "ERROR_CODE_INDEPENDENT_APPROVAL_REQUIRED",
        "ERROR_CODE_OPERATOR_AUTHORITY_REQUIRED",
        "ERROR_CODE_TENANT_AXIS_MISSING",
        "OPERATOR_CAPABILITY",
        "PLATFORM_TENANT_ADMIN_CAPABILITY",       # spec 2.5c platform lifecycle
        "TENANT_ACTIONS_APPROVE_CAPABILITY",    # spec 1a-ext #26
        "TENANT_ADMIN_CAPABILITY",
        "TENANT_APPROVALS_READ_CAPABILITY",      # spec Fix 1b approvals
        "TENANT_AUDIT_EXPORT_CAPABILITY",        # spec 1a #80
        "TENANT_CHANNEL_ADMIN_CAPABILITY",
        "TENANT_COGNITION_READ_CAPABILITY",      # spec 1a-ext #26
        "TENANT_CONFIG_APPROVE_CAPABILITY",
        "TENANT_CONFIG_DOMAIN_WRITE_CAPABILITIES",
        "TENANT_CONFIG_READ_CAPABILITY",
        "TENANT_CONFIG_WRITE_CAPABILITY",
        "TENANT_CONNECTOR_APPROVE_CAPABILITY",   # spec 2.5a connector approval
        "TENANT_CONNECTOR_READ_CAPABILITY",       # spec 2.5b connector read
        "TENANT_CONNECTOR_WRITE_CAPABILITY",       # spec 2.5a connector config
        "TENANT_EXECUTION_GOVERNANCE_WRITE_CAPABILITY",
        "TENANT_GOVERNANCE_READ_CAPABILITY",     # spec 1a-ext #26
        "TENANT_KNOWLEDGE_APPROVE_CAPABILITY",   # security fix F7: dual-control
        "TENANT_KNOWLEDGE_WRITE_CAPABILITY",
        "TENANT_OBSERVABILITY_READ_CAPABILITY",  # spec 1a #26
        "TENANT_OPERATIONS_READ_CAPABILITY",      # spec 1a-ext #26
        "TENANT_POLICY_WRITE_CAPABILITY",
        "TENANT_PRIVACY_ADMIN_CAPABILITY",        # spec 1c-ext
        "TENANT_PRIVACY_APPROVE_CAPABILITY",      # spec 1c-ext
        "TENANT_RESOLUTION_GUIDE_CAPABILITY",     # spec Fix 1b guidance
        "TENANT_SUPERVISOR_READ_CAPABILITY",     # spec 1a-ext #26
        "TENANT_TOPOLOGY_WRITE_CAPABILITY",
        "TENANT_TRAINING_WRITE_CAPABILITY",       # spec 1a-ext #26
        "request_authority_opt",
        "request_tenant_scope_opt",
        "require_authority",
        "require_capability",
        "require_config_apply_authorization",
        "require_config_apply_authorization_for",
        "require_operator_authority",
        "require_platform_tenant_admin",         # spec 2.5c platform lifecycle
        "require_tenant_actions_approve",        # spec 1a-ext #26
        "require_tenant_admin",
        "require_tenant_approvals_read",         # spec Fix 1b approvals
        "require_tenant_audit_export",           # spec 1a #80
        "require_tenant_cognition_read",         # spec 1a-ext #26
        "require_tenant_connector_approve",      # spec 2.5a connector approval
        "require_tenant_connector_read",          # spec 2.5b connector read
        "require_tenant_governance_read",        # spec 1a-ext #26
        "require_tenant_knowledge_approve",      # security fix F7: dual-control
        "require_tenant_knowledge_write",        # spec 1a-ext #26
        "require_tenant_observability_read",     # spec 1a #26
        "require_tenant_operations_read",        # spec 1a-ext #26
        "require_tenant_privacy_admin",          # spec 1c-ext
        "require_tenant_privacy_approve",        # spec 1c-ext
        "require_tenant_resolution_guide",       # spec Fix 1b guidance
        "require_tenant_scope",
        "require_tenant_supervisor_read",        # spec 1a-ext #26
        "require_tenant_training_write",         # spec 1a-ext #26
    ]


def test_package_re_exports_helpers() -> None:
    """The helpers MUST be importable from ``app.dependencies``
    directly so endpoint authors do not reach into submodules.
    This is the single canonical import path."""
    import app.dependencies as deps

    assert deps.require_tenant_scope is require_tenant_scope
    assert deps.require_authority is require_authority
    assert deps.require_operator_authority is require_operator_authority
    assert deps.require_platform_tenant_admin is require_platform_tenant_admin
    assert deps.OPERATOR_CAPABILITY == OPERATOR_CAPABILITY
    assert (
        deps.PLATFORM_TENANT_ADMIN_CAPABILITY
        == PLATFORM_TENANT_ADMIN_CAPABILITY
    )
    assert (
        deps.ERROR_CODE_OPERATOR_AUTHORITY_REQUIRED
        == ERROR_CODE_OPERATOR_AUTHORITY_REQUIRED
    )
    assert deps.request_tenant_scope_opt is request_tenant_scope_opt
    assert deps.request_authority_opt is request_authority_opt
