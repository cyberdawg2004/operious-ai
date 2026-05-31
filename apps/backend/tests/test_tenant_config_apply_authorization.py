"""Separation of duties for tenant config application (S-03).

The tenant configuration service mints the approval that the runtime
requires before a knowledge / policy / execution-governance change is
applied. Previously it self-approved with ``reviewed_by == proposed_by``
and no distinct capability, so any tenant-admin could silently approve
their own governance change.

``require_config_apply_authorization`` now keeps that old direct path
behind an explicit non-production flag. Production must use the durable
change-request ledger even if the caller also holds
``tenant.config.approve``.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.core.config import get_settings
from app.dependencies.authority import (
    ERROR_CODE_INDEPENDENT_APPROVAL_REQUIRED,
    TENANT_CONFIG_APPROVE_CAPABILITY,
    require_config_apply_authorization,
)
from app.identity.authority import AuthorityContext
from app.identity.primitives import PrincipalId, TenantId


def _admin(*, approver: bool = False) -> AuthorityContext:
    caps = {"tenant_admin"}
    if approver:
        caps.add(TENANT_CONFIG_APPROVE_CAPABILITY)
    return AuthorityContext(
        tenant_id=TenantId("acme"),
        principal_id=PrincipalId("admin-1"),
        capabilities=frozenset(caps),
    )


@pytest.fixture(autouse=True)
def _clear_settings():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_non_production_allows_self_approval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ENVIRONMENT", "staging")
    monkeypatch.setenv("TENANT_CONFIG_ALLOW_SELF_APPROVAL", "true")
    get_settings.cache_clear()
    authority = _admin()
    # Called directly with the resolved authority (FastAPI would resolve
    # it via Depends(require_tenant_admin)).
    assert require_config_apply_authorization(authority) is authority


def test_production_requires_distinct_approve_capability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    get_settings.cache_clear()
    with pytest.raises(HTTPException) as exc:
        require_config_apply_authorization(_admin(approver=False))
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == ERROR_CODE_INDEPENDENT_APPROVAL_REQUIRED


def test_production_blocks_even_when_approve_capability_held(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    get_settings.cache_clear()
    with pytest.raises(HTTPException) as exc:
        require_config_apply_authorization(_admin(approver=True))
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == ERROR_CODE_INDEPENDENT_APPROVAL_REQUIRED


def test_explicit_self_approval_override_in_production_still_blocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("TENANT_CONFIG_ALLOW_SELF_APPROVAL", "true")
    get_settings.cache_clear()
    with pytest.raises(HTTPException) as exc:
        require_config_apply_authorization(_admin())
    assert exc.value.status_code == 403
