"""2.5-F: ``GovernanceContext`` extension invariants.

Pinned properties:

* the new typed identity axes (``principal_id``, ``organization_id``,
  ``environment_id``) are surfaced and remain optional,
* a populated ``authority`` reference and a populated ``tenant_id``
  must agree on the tenant axis (``__post_init__`` guard),
* legacy callers that only pass ``tenant_id`` continue to work,
* legacy callers that pass neither ``authority`` nor ``tenant_id``
  continue to work.
"""

from __future__ import annotations

import pytest

from app.governance.context import GovernanceContext
from app.governance.enums import EnforcementStage
from app.governance.exceptions import GovernanceConfigurationError
from app.identity import (
    AuthorityContext,
    EnvironmentId,
    OrganizationId,
    PrincipalId,
    TenantId,
)


def test_governance_context_accepts_typed_identity_axes() -> None:
    ctx = GovernanceContext(
        stage=EnforcementStage.PRE_RETRIEVAL,
        action="rag.assemble_context",
        resource="tenant:acme/index:default",
        tenant_id=TenantId("acme"),
        principal_id=PrincipalId("user-1"),
        organization_id=OrganizationId("org-acme"),
        environment_id=EnvironmentId("prod"),
    )
    assert ctx.tenant_id == "acme"
    assert ctx.principal_id == "user-1"
    assert ctx.organization_id == "org-acme"
    assert ctx.environment_id == "prod"
    assert ctx.authority is None


def test_governance_context_accepts_authority_reference() -> None:
    authority = AuthorityContext.from_raw(
        tenant_id="acme",
        principal_id="user-1",
        organization_id="org-acme",
        environment_id="prod",
    )
    ctx = GovernanceContext(
        stage=EnforcementStage.PRE_RETRIEVAL,
        action="rag.assemble_context",
        resource="tenant:acme/index:default",
        tenant_id=TenantId("acme"),
        authority=authority,
    )
    assert ctx.authority is authority
    assert ctx.tenant_id == ctx.authority.tenant_id


def test_governance_context_rejects_tenant_authority_drift() -> None:
    """The dual-source-of-truth invariant — if both fields are set,
    they MUST agree on the tenant axis. Without this guard the two
    fields silently drift in production.
    """
    authority = AuthorityContext.from_raw(tenant_id="acme")
    with pytest.raises(GovernanceConfigurationError):
        GovernanceContext(
            stage=EnforcementStage.PRE_RETRIEVAL,
            action="rag.assemble_context",
            resource="tenant:other/index:default",
            tenant_id=TenantId("other"),
            authority=authority,
        )


def test_governance_context_allows_authority_without_tenant_id() -> None:
    """A populated ``authority`` with ``tenant_id=None`` on the
    context is fine — the invariant only fires on disagreement.
    """
    authority = AuthorityContext.from_raw(tenant_id="acme")
    ctx = GovernanceContext(
        stage=EnforcementStage.PRE_RETRIEVAL,
        action="rag.assemble_context",
        resource="tenant:acme/index:default",
        authority=authority,
    )
    assert ctx.tenant_id is None
    assert ctx.authority is authority


def test_governance_context_legacy_call_still_works() -> None:
    """Callers that only set ``tenant_id`` (no authority, no other
    typed axes) continue to compile and behave like before."""
    ctx = GovernanceContext(
        stage=EnforcementStage.PRE_RETRIEVAL,
        action="rag.assemble_context",
        resource="tenant:acme/index:default",
        tenant_id=TenantId("acme"),
    )
    assert ctx.principal_id is None
    assert ctx.organization_id is None
    assert ctx.environment_id is None
    assert ctx.authority is None
