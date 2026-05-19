"""Phase 2.75-γ regression tests — full authority axis in builders.

Constitutional guarantees:

* :class:`GovernanceContext.__post_init__` enforces a four-axis
  coexistence invariant: ``tenant_id``, ``principal_id``,
  ``organization_id``, ``environment_id`` MUST agree with the
  corresponding fields of ``authority`` when both are present.
  Mirrors the tenant invariant that was already in place (2.5-F).

* Every GovernanceContext builder under audit
  (``build_capability_context``, coordination
  ``_build_governance_context``, agent-tool
  ``_build_governance_context``) projects the full authority axis
  onto the resulting context. Dropping principal / organization /
  environment here would have produced policy decisions whose
  trace records lacked the requesting principal's attribution.
"""

from __future__ import annotations

import uuid

import pytest

from app.agents.capabilities import (
    CapabilitySet,
    ExecutionConstraints,
)
from app.agents.context import AgentExecutionContext
from app.agents.identity import AgentIdentity, ExecutionIdentity
from app.agents.value_objects import CausalityMetadata
from app.coordination.contracts.messages import (
    CoordinationMessage,
)
from app.coordination.contracts.requests import (
    CoordinationDispatchRequest,
)
from app.coordination.enums import (
    CoordinationDirection,
    CoordinationMessageType,
    CoordinationPriority,
)
from app.coordination.identity import generate_message_id
from app.coordination.models.payload import CoordinationPayload
from app.coordination.models.recipients import CoordinationRecipient
from app.governance.capability.acts import OperationalAct
from app.governance.capability.gate import (
    CapabilityLegalityRequest,
    build_capability_context,
)
from app.governance.context import GovernanceContext
from app.governance.enums import EnforcementStage
from app.governance.exceptions import GovernanceConfigurationError
from app.governance.subjects.base import GenericGovernanceSubject
from app.identity import (
    AuthorityContext,
    AuthorityResolution,
    AuthoritySource,
    EnvironmentId,
    OrganizationId,
    PrincipalId,
    TenantId,
)


# ─── Schema coexistence invariants ─────────────────────────────────


def test_principal_axis_coexistence_invariant_rejects_drift() -> None:
    authority = AuthorityContext(
        tenant_id=TenantId("tenant-1"),
        principal_id=PrincipalId("alice"),
    )
    with pytest.raises(GovernanceConfigurationError) as exc:
        GovernanceContext(
            stage=EnforcementStage.PRE_REQUEST,
            action="act",
            resource="r",
            tenant_id=TenantId("tenant-1"),
            principal_id=PrincipalId("bob"),
            authority=authority,
            subject=GenericGovernanceSubject(),
        )
    assert "principal_id" in str(exc.value)


def test_organization_axis_coexistence_invariant_rejects_drift() -> None:
    authority = AuthorityContext(
        tenant_id=TenantId("tenant-1"),
        organization_id=OrganizationId("org-A"),
    )
    with pytest.raises(GovernanceConfigurationError) as exc:
        GovernanceContext(
            stage=EnforcementStage.PRE_REQUEST,
            action="act",
            resource="r",
            tenant_id=TenantId("tenant-1"),
            organization_id=OrganizationId("org-B"),
            authority=authority,
            subject=GenericGovernanceSubject(),
        )
    assert "organization_id" in str(exc.value)


def test_environment_axis_coexistence_invariant_rejects_drift() -> None:
    authority = AuthorityContext(
        tenant_id=TenantId("tenant-1"),
        environment_id=EnvironmentId("prod"),
    )
    with pytest.raises(GovernanceConfigurationError) as exc:
        GovernanceContext(
            stage=EnforcementStage.PRE_REQUEST,
            action="act",
            resource="r",
            tenant_id=TenantId("tenant-1"),
            environment_id=EnvironmentId("staging"),
            authority=authority,
            subject=GenericGovernanceSubject(),
        )
    assert "environment_id" in str(exc.value)


def test_coexistence_invariants_allow_none_on_either_side() -> None:
    """``None`` on either side is a constitutionally legal absence.

    The invariant only fires when BOTH the flat field and the
    authority's matching field are populated and disagree.
    """
    authority = AuthorityContext(
        tenant_id=TenantId("tenant-1"),
        principal_id=None,
        organization_id=None,
        environment_id=None,
    )
    context = GovernanceContext(
        stage=EnforcementStage.PRE_REQUEST,
        action="act",
        resource="r",
        tenant_id=TenantId("tenant-1"),
        principal_id=PrincipalId("alice"),
        organization_id=OrganizationId("org-A"),
        environment_id=EnvironmentId("prod"),
        authority=authority,
        subject=GenericGovernanceSubject(),
    )
    assert context.principal_id == PrincipalId("alice")
    assert context.organization_id == OrganizationId("org-A")
    assert context.environment_id == EnvironmentId("prod")


# ─── build_capability_context: full axis projection ────────────────


def test_capability_context_projects_all_authority_axes() -> None:
    authority = AuthorityContext(
        tenant_id=TenantId("tenant-1"),
        principal_id=PrincipalId("alice"),
        organization_id=OrganizationId("org-A"),
        environment_id=EnvironmentId("prod"),
        capabilities=frozenset({"session.open"}),
    )
    ctx = build_capability_context(
        CapabilityLegalityRequest(
            authority=authority,
            act=OperationalAct.SESSION_OPEN,
            actor="session_runtime",
        )
    )
    assert ctx.tenant_id == TenantId("tenant-1")
    assert ctx.principal_id == PrincipalId("alice")
    assert ctx.organization_id == OrganizationId("org-A")
    assert ctx.environment_id == EnvironmentId("prod")
    assert ctx.authority is authority


def test_capability_context_propagates_none_axes() -> None:
    authority = AuthorityContext(tenant_id=TenantId("tenant-1"))
    ctx = build_capability_context(
        CapabilityLegalityRequest(
            authority=authority,
            act=OperationalAct.SESSION_OPEN,
        )
    )
    assert ctx.principal_id is None
    assert ctx.organization_id is None
    assert ctx.environment_id is None
    assert ctx.authority is authority


# ─── coordination._build_governance_context: full axis projection ──


def _coord_request(
    *,
    authority: AuthorityContext | None,
) -> CoordinationDispatchRequest:
    return CoordinationDispatchRequest(
        message=CoordinationMessage(
            message_id=generate_message_id(),
            message_type=CoordinationMessageType.HANDOFF,
            sender_id="agent:A",
            recipient=CoordinationRecipient(
                recipient_id="agent:B",
                kind="agent",
                tenant_id="tenant-1",
            ),
            payload=CoordinationPayload(
                content_type="application/json",
                body={"x": 1},
            ),
            priority=CoordinationPriority.NORMAL,
        ),
        direction=CoordinationDirection.AGENT_TO_AGENT,
        tenant_id="tenant-1",
        authority=authority,
    )


def test_coordination_context_projects_all_authority_axes() -> None:
    authority = AuthorityContext(
        tenant_id=TenantId("tenant-1"),
        principal_id=PrincipalId("alice"),
        organization_id=OrganizationId("org-A"),
        environment_id=EnvironmentId("prod"),
    )
    request = _coord_request(authority=authority)
    resolution = AuthorityResolution(
        tenant_id="tenant-1",
        source=AuthoritySource.TYPED_AUTHORITY,
    )
    ctx = _invoke_coord_builder(request, resolution)
    assert ctx.tenant_id == TenantId("tenant-1")
    assert ctx.principal_id == PrincipalId("alice")
    assert ctx.organization_id == OrganizationId("org-A")
    assert ctx.environment_id == EnvironmentId("prod")
    assert ctx.authority is authority


def test_coordination_context_drops_axes_only_when_no_authority() -> None:
    request = _coord_request(authority=None)
    resolution = AuthorityResolution(
        tenant_id="tenant-1",
        source=AuthoritySource.LEGACY_TENANT,
    )
    ctx = _invoke_coord_builder(request, resolution)
    assert ctx.tenant_id == TenantId("tenant-1")
    assert ctx.principal_id is None
    assert ctx.organization_id is None
    assert ctx.environment_id is None
    assert ctx.authority is None


def _invoke_coord_builder(
    request: CoordinationDispatchRequest,
    resolution: AuthorityResolution,
) -> GovernanceContext:
    """Bind the bound-method to a no-op instance via descriptor.

    The coordination builder is a method on ``CoordinationRuntime``
    that only consumes its arguments and never touches ``self``
    state when called for context construction — it reads no
    attribute and emits no side effect. Constructing a real
    runtime here would require its full dependency graph; binding
    the unbound function directly avoids that overhead while
    preserving identical semantics.
    """
    from app.coordination.runtime.runtime import CoordinationRuntime

    func = CoordinationRuntime._build_governance_context
    # The method has signature (self, *, request, request_id, resolution).
    # Pass a sentinel for ``self``; the body never reads it.
    return func(
        None,  # type: ignore[arg-type]
        request=request,
        request_id="req-1",
        resolution=resolution,
    )


# ─── agent_tools._build_governance_context: full axis projection ───


def _agent_context(
    *,
    authority: AuthorityContext | None,
    tenant_id: str | None = "tenant-1",
) -> AgentExecutionContext:
    return AgentExecutionContext(
        identity=AgentIdentity(
            agent_id="agent-A",
            runtime_instance_id=uuid.uuid4(),
        ),
        execution=ExecutionIdentity(
            execution_id=uuid.uuid4(),
            correlation_id=uuid.uuid4(),
            parent_execution_id=None,
            request_id="req-1",
        ),
        capabilities=CapabilitySet(capabilities=()),
        constraints=ExecutionConstraints(),
        causality=CausalityMetadata(),
        tenant_id=tenant_id,
        authority=authority,
    )


def test_agent_tool_context_projects_all_authority_axes() -> None:
    from app.agents.results import ToolInvocationRequest
    from app.agents.tools.invoker import _build_governance_context

    class _StubTool:
        name = "search"
        required_capabilities: frozenset[str] = frozenset(
            {"agent.search"}
        )

    authority = AuthorityContext(
        tenant_id=TenantId("tenant-1"),
        principal_id=PrincipalId("alice"),
        organization_id=OrganizationId("org-A"),
        environment_id=EnvironmentId("prod"),
    )
    context = _agent_context(authority=authority)
    ctx = _build_governance_context(
        ToolInvocationRequest(
            tool_name="search",
            payload={"q": "x"},
        ),
        context,
        _StubTool(),  # type: ignore[arg-type]
    )
    assert ctx.tenant_id == TenantId("tenant-1")
    assert ctx.principal_id == PrincipalId("alice")
    assert ctx.organization_id == OrganizationId("org-A")
    assert ctx.environment_id == EnvironmentId("prod")
    assert ctx.authority is authority


def test_agent_tool_context_no_authority_yields_none_axes() -> None:
    from app.agents.results import ToolInvocationRequest
    from app.agents.tools.invoker import _build_governance_context

    class _StubTool:
        name = "search"
        required_capabilities: frozenset[str] = frozenset()

    context = _agent_context(authority=None)
    ctx = _build_governance_context(
        ToolInvocationRequest(
            tool_name="search",
            payload={"q": "x"},
        ),
        context,
        _StubTool(),  # type: ignore[arg-type]
    )
    assert ctx.tenant_id == TenantId("tenant-1")
    assert ctx.principal_id is None
    assert ctx.organization_id is None
    assert ctx.environment_id is None
    assert ctx.authority is None
