"""Composition-root tenant-scope dependency contract.

Pins the behaviour of ``app.dependencies.authority`` against
the constitutional contract established by Wedge 2.75-ε:

* :func:`require_tenant_scope` rejects anonymous and tenant-less
  authorities. This is the wedge that future tenant-scoped read
  handlers transitively depend on.
* :func:`require_authority` rejects anonymous only.
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

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.dependencies.authority import (
    ERROR_CODE_AUTHORITY_REQUIRED,
    ERROR_CODE_TENANT_AXIS_MISSING,
    request_authority_opt,
    request_tenant_scope_opt,
    require_authority,
    require_tenant_scope,
)
from app.identity.authority import AuthorityContext
from app.identity.primitives import TenantId


def _request(authority: AuthorityContext | None = None) -> Request:
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
    return req


# ─── require_authority ──────────────────────────────────────────────


def test_require_authority_returns_bound_authority() -> None:
    authority = AuthorityContext(tenant_id=TenantId("acme"))
    assert require_authority(_request(authority)) is authority


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
    misconfiguration. The platform refuses with 400."""
    authority = AuthorityContext()  # no tenant_id, no principal_id
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
    handlers using this dependency are unconstrained."""
    authority = AuthorityContext()
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
        "ERROR_CODE_TENANT_AXIS_MISSING",
        "request_authority_opt",
        "request_tenant_scope_opt",
        "require_authority",
        "require_tenant_scope",
    ]


def test_package_re_exports_helpers() -> None:
    """The helpers MUST be importable from ``app.dependencies``
    directly so endpoint authors do not reach into submodules.
    This is the single canonical import path."""
    import app.dependencies as deps

    assert deps.require_tenant_scope is require_tenant_scope
    assert deps.require_authority is require_authority
    assert deps.request_tenant_scope_opt is request_tenant_scope_opt
    assert deps.request_authority_opt is request_authority_opt
