"""Security fixes for MVP-2 custom tool governance.

Finding 1 — Money/goods commitment_kind enforcement in _evaluate_custom_tool:
  A custom tool with commitment_kind=money/goods MUST ALWAYS route to human
  approval regardless of the tenant's declared 'decision' field.

Finding 1b — Money/goods stub tools cannot return simulated success:
  build_tenant_action_tool_registry must never register a fake-success stub
  for money/goods operations (warranty, refund, replacement), even when
  allow_stub_actions=True.  Only non-committing tools (warehouse repair report)
  may use stubs.

Finding 2 — Misdeclaration backstop:
  When a custom tool is declared commitment_kind=none/record_update but the
  governance context carries money/goods metadata signals (e.g. refund_amount_cents
  present, or operation_commitment_kind=money in metadata), the conflict must
  route to human rather than trusting the declaration blindly.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from app.agents.tools.action_governance import (
    ACTION_TOOLS_POLICY_TYPE,
    ActionPolicyBinding,
    CustomToolDeclaration,
    ParsedActionPolicy,
    TenantActionPolicy,
    _evaluate_custom_tool,
    _metadata_money_goods_conflict,
)
from app.agents.tools.operation_metadata import CommitmentKind
from app.governance.enums import Decision
from app.tenant.chronology import canonical_sha256
from app.tenant.enums import TenantGovernancePolicyStatus
from app.tenant.identity import derive_governance_policy_version_id
from app.tenant.persistence import (
    InMemoryTenantConfigurationRepository,
    TenantGovernancePolicyRecord,
)

_NOW = datetime(2026, 7, 3, tzinfo=timezone.utc)
_TENANT = "tenant-security-fix-tests"
_APPROVAL_ID = "approval-security"
_APPROVED_BY = "admin"


def _binding() -> ActionPolicyBinding:
    return ActionPolicyBinding(
        policy_id="p1",
        policy_type=ACTION_TOOLS_POLICY_TYPE,
        version=1,
        content_sha256="a" * 64,
    )


def _policy_with_custom_tool(
    tool_name: str,
    commitment_kind: CommitmentKind,
    decision: Decision,
) -> ParsedActionPolicy:
    return ParsedActionPolicy(
        binding=_binding(),
        rules={},
        custom_tools={
            tool_name: CustomToolDeclaration(
                tool_name=tool_name,
                commitment_kind=commitment_kind,
                decision=decision,
            )
        },
    )


# ---------------------------------------------------------------------------
# Finding 1 — money/goods commitment_kind always routes to human
# ---------------------------------------------------------------------------


def test_custom_money_tool_decision_allow_routes_to_human() -> None:
    """A custom tool with commitment_kind=money MUST NOT return ALLOW even if
    the tenant declared decision=allow.  The money/goods invariant overrides."""
    policy = _policy_with_custom_tool(
        "account.credit", CommitmentKind.MONEY, Decision.ALLOW
    )
    result = _evaluate_custom_tool(tool_name="account.credit", policy=policy)
    assert result[0].decision == Decision.REQUIRE_APPROVAL
    assert "money" in result[0].reason.lower() or "goods" in result[0].reason.lower()


def test_custom_goods_tool_decision_allow_routes_to_human() -> None:
    """Same invariant for commitment_kind=goods."""
    policy = _policy_with_custom_tool(
        "device.replace", CommitmentKind.GOODS, Decision.ALLOW
    )
    result = _evaluate_custom_tool(tool_name="device.replace", policy=policy)
    assert result[0].decision == Decision.REQUIRE_APPROVAL


def test_custom_money_tool_decision_deny_still_routes_to_human() -> None:
    """Even decision=deny for a money tool: REQUIRE_APPROVAL (not DENY).
    The money/goods gate always picks REQUIRE_APPROVAL to allow human review,
    not DENY which would permanently block the action."""
    policy = _policy_with_custom_tool(
        "account.credit", CommitmentKind.MONEY, Decision.DENY
    )
    result = _evaluate_custom_tool(tool_name="account.credit", policy=policy)
    # The money/goods inviolable gate fires before decision check → REQUIRE_APPROVAL
    assert result[0].decision == Decision.REQUIRE_APPROVAL


def test_custom_none_commitment_decision_allow_returns_allow() -> None:
    """A custom tool with commitment_kind=none + decision=allow IS allowed.
    The money/goods override does NOT fire for non-committing tools."""
    policy = _policy_with_custom_tool(
        "info.query", CommitmentKind.NONE, Decision.ALLOW
    )
    result = _evaluate_custom_tool(tool_name="info.query", policy=policy)
    assert result[0].decision == Decision.ALLOW


def test_custom_record_update_decision_allow_returns_allow() -> None:
    """commitment_kind=record_update + decision=allow → ALLOW (not money/goods)."""
    policy = _policy_with_custom_tool(
        "ticket.update", CommitmentKind.RECORD_UPDATE, Decision.ALLOW
    )
    result = _evaluate_custom_tool(tool_name="ticket.update", policy=policy)
    assert result[0].decision == Decision.ALLOW


# ---------------------------------------------------------------------------
# Finding 1 — Governance runs before any stub path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_governance_before_stub_money_tool_denied_not_stubbed_to_success() -> None:
    """A custom money tool that governance denies (REQUIRE_APPROVAL) MUST NOT
    be stubbed to success — governance runs first and the result is final."""
    from app.governance.subjects.agent_actions import AgentActionGovernanceSubject
    from app.governance.context import GovernanceContext
    from app.governance.enums import EnforcementStage
    from app.identity import TenantId

    repository = InMemoryTenantConfigurationRepository()
    # Register policy with money custom tool declared as decision=allow (the hole we fixed)
    record = _policy_record(
        tenant_id=_TENANT,
        tools={"account.credit": {"commitment_kind": "money", "decision": "allow"}}
    )
    await repository.save_governance_policy(record, expected_tenant_id=_TENANT)

    policy_instance = TenantActionPolicy(repository=repository)
    subject = AgentActionGovernanceSubject(
        tool_name="account.credit",
        tenant_id=_TENANT,
        metadata={"tool_name": "account.credit"},
    )
    context = GovernanceContext(
        stage=EnforcementStage.PRE_EXECUTION,
        action="tool.account.credit",
        resource="tool:account.credit",
        tenant_id=TenantId(_TENANT),
        subject=subject,
    )
    results = await policy_instance.evaluate(context)
    assert results
    # The money/goods override must prevent ALLOW
    assert results[0].decision != Decision.ALLOW
    assert results[0].decision == Decision.REQUIRE_APPROVAL


# ---------------------------------------------------------------------------
# Finding 1b — Money/goods stubs cannot return simulated success
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unconfigured_money_goods_tools_absent_from_registry() -> None:
    """Money/goods tools (warranty, refund, replacement) are absent from the registry
    when not configured. Domain-agnostic: no hardcoded tool names are pre-registered.
    An unconfigured tenant has no tools — no stub, no FailClosedActionTool placeholder.
    The agent session's unknown-tool path provides the governed error.
    """
    from app.agents.tools.actions import build_tenant_action_tool_registry
    from app.agents.exceptions import ToolNotFoundError
    from app.agents.tools.connectors.config import InMemoryConnectorConfigRepository

    registry = await build_tenant_action_tool_registry(
        tenant_id=_TENANT,
        config_repository=InMemoryConnectorConfigRepository(),
        credential_runtime=_DummyCredentialRuntime(),
        allow_stub_actions=True,
    )
    assert registry.names() == (), (
        "unconfigured tenant must have empty registry — "
        "no hardcoded e-commerce tool stubs"
    )
    for name in ("warranty.claim", "refund.request", "replacement.order",
                 "warehouse.repair.report"):
        try:
            registry.get(name)
            pytest.fail(f"{name!r} should not be in registry when unconfigured")
        except ToolNotFoundError:
            pass  # expected


@pytest.mark.asyncio
async def test_configured_money_goods_connector_has_always_require_approval() -> None:
    """A configured money/goods connector gets ALWAYS_REQUIRE_APPROVAL.

    CommitmentKind is derived from connector_type prefix — a 'money.*' or
    'goods.*' connector always requires human approval regardless of tenant
    policy configuration. This is the replacement for the old
    FailClosedActionTool stub test: the invariant now lives in commitment_kind.
    """
    from app.agents.tools.actions import build_tenant_action_tool_registry
    from app.agents.tools.connectors import GenericConnectorTool
    from app.agents.tools.connectors.config import (
        ConnectorConfigRecord,
        InMemoryConnectorConfigRepository,
    )
    from app.agents.tools.operation_metadata import ApprovalPolicy, CommitmentKind

    repo = InMemoryConnectorConfigRepository()
    for connector_type, tool_name in (
        ("money.refund", "refund.request"),
        ("goods.warranty", "warranty.claim"),
        ("goods.replacement", "replacement.order"),
    ):
        await repo.save_config(
            ConnectorConfigRecord(
                tenant_id=_TENANT,
                connector_type=connector_type,
                tool_name=tool_name,
                http_method="POST",
                endpoint_template=f"https://example.com/{tool_name}",
                endpoint_host="example.com",
            ),
            expected_tenant_id=_TENANT,
        )

    registry = await build_tenant_action_tool_registry(
        tenant_id=_TENANT,
        config_repository=repo,
        credential_runtime=_DummyCredentialRuntime(),
        allow_stub_actions=False,
    )
    for tool_name in ("refund.request", "warranty.claim", "replacement.order"):
        tool = registry.get(tool_name)
        assert isinstance(tool, GenericConnectorTool), (
            f"{tool_name!r} expected GenericConnectorTool, got {type(tool).__name__}"
        )
        op = tool.operation_definition
        assert op.approval_policy is ApprovalPolicy.ALWAYS_REQUIRE_APPROVAL, (
            f"{tool_name!r} must require approval — money/goods-always-human invariant"
        )
        assert op.commitment_kind in (CommitmentKind.MONEY, CommitmentKind.GOODS), (
            f"{tool_name!r} commitment_kind must be MONEY or GOODS"
        )


@pytest.mark.asyncio
async def test_unconfigured_registry_empty_in_production() -> None:
    """allow_stub_actions=False (production default): empty registry for unconfigured tenant."""
    from app.agents.tools.actions import build_tenant_action_tool_registry
    from app.agents.tools.connectors.config import InMemoryConnectorConfigRepository

    registry = await build_tenant_action_tool_registry(
        tenant_id=_TENANT,
        config_repository=InMemoryConnectorConfigRepository(),
        credential_runtime=_DummyCredentialRuntime(),
        allow_stub_actions=False,
    )
    assert registry.names() == (), (
        "production unconfigured tenant must have empty registry"
    )


@pytest.mark.asyncio
async def test_fail_closed_tool_invoke_returns_error_not_success() -> None:
    """FailClosedActionTool invocation always returns an error result.

    Updated: no longer built from the registry (tools are only in the registry
    when configured). FailClosedActionTool is constructed directly to test the
    invariant — its error behavior is independent of how it gets into the registry.
    """
    from app.agents.tools.actions.fail_closed import FailClosedActionTool
    from app.agents.tools.base import ToolCapability
    from app.agents.results import ToolInvocationRequest
    from app.agents.context import AgentExecutionContext
    from app.agents.capabilities import CapabilitySet, ExecutionConstraints
    from app.agents.identity import AgentIdentity, ExecutionIdentity
    from app.agents.value_objects import CausalityMetadata
    import uuid

    warranty_tool = FailClosedActionTool(
        name="warranty.claim",
        capability=ToolCapability.ACTION,
        required_capabilities=frozenset({"tool.warranty.claim"}),
        reason="warranty connector not configured for this tenant",
    )
    request = ToolInvocationRequest(
        tool_name="warranty.claim",
        payload={"order_id": "ORD-1", "product_sku": "SKU-1",
                 "issue_category": "defective", "customer_description": "broken"},
        metadata={},
    )
    context = AgentExecutionContext(
        identity=AgentIdentity(
            agent_id="test", runtime_instance_id=uuid.uuid5(uuid.NAMESPACE_URL, "t")
        ),
        execution=ExecutionIdentity(
            execution_id=uuid.uuid5(uuid.NAMESPACE_URL, "e"), request_id="r"
        ),
        capabilities=CapabilitySet(()),
        constraints=ExecutionConstraints(),
        causality=CausalityMetadata(),
        tenant_id=_TENANT,
        metadata={},
    )
    result = await warranty_tool.invoke(request, context)
    assert result.status == "error", (
        f"FailClosedActionTool must return error status, not {result.status!r}."
    )
    assert result.output.get("status") == "error"


# ---------------------------------------------------------------------------
# Finding 2 — Misdeclaration backstop
# ---------------------------------------------------------------------------


def test_misdeclaration_backstop_refund_amount_in_none_tool() -> None:
    """A custom tool declared commitment_kind=none but with refund_amount_cents
    in metadata → routed to human as a precaution."""
    policy = _policy_with_custom_tool(
        "account.process", CommitmentKind.NONE, Decision.ALLOW
    )
    metadata_with_refund: dict[str, object] = {
        "tool_name": "account.process",
        "refund_amount_cents": 5000,  # clearly a money signal
    }
    result = _evaluate_custom_tool(
        tool_name="account.process",
        policy=policy,
        subject_metadata=metadata_with_refund,
    )
    assert result[0].decision == Decision.REQUIRE_APPROVAL, (
        "A tool declared commitment_kind=none with refund_amount_cents in metadata "
        "must route to human — misdeclaration backstop must fire."
    )
    assert "misdeclaration" in result[0].reason.lower() or "conflict" in result[0].reason.lower() or \
           "precaution" in result[0].reason.lower()


def test_misdeclaration_backstop_explicit_money_kind_in_metadata() -> None:
    """operation_commitment_kind=money in metadata while declared as none → human."""
    policy = _policy_with_custom_tool(
        "account.process", CommitmentKind.NONE, Decision.ALLOW
    )
    metadata: dict[str, object] = {
        "tool_name": "account.process",
        "operation_commitment_kind": "money",
    }
    result = _evaluate_custom_tool(
        tool_name="account.process",
        policy=policy,
        subject_metadata=metadata,
    )
    assert result[0].decision == Decision.REQUIRE_APPROVAL


def test_misdeclaration_backstop_no_signal_allows() -> None:
    """A none commitment_kind tool with no money metadata → ALLOW as declared.
    The backstop must NOT fire false positives on innocent non-money tools."""
    policy = _policy_with_custom_tool(
        "info.query", CommitmentKind.NONE, Decision.ALLOW
    )
    metadata: dict[str, object] = {
        "tool_name": "info.query",
        "account_number": "ACC-123",
        "session_id": "sess-1",
    }
    result = _evaluate_custom_tool(
        tool_name="info.query",
        policy=policy,
        subject_metadata=metadata,
    )
    assert result[0].decision == Decision.ALLOW, (
        "A non-committing tool with no money signals must be ALLOW — "
        "backstop must not cause false positives."
    )


def test_metadata_money_goods_conflict_returns_none_for_no_signal() -> None:
    """_metadata_money_goods_conflict returns None when no money signal present."""
    conflict = _metadata_money_goods_conflict(
        {"account_number": "ACC-1", "session_id": "s"},
        declared_kind=CommitmentKind.NONE,
    )
    assert conflict is None


def test_metadata_money_goods_conflict_returns_description_for_refund_cents() -> None:
    conflict = _metadata_money_goods_conflict(
        {"refund_amount_cents": 1000},
        declared_kind=CommitmentKind.NONE,
    )
    assert conflict is not None
    assert "refund_amount_cents" in conflict


def test_metadata_money_goods_conflict_zero_refund_not_flagged() -> None:
    """Zero refund_amount_cents is not a money signal (zero-value, no commitment)."""
    conflict = _metadata_money_goods_conflict(
        {"refund_amount_cents": 0},
        declared_kind=CommitmentKind.NONE,
    )
    assert conflict is None


def test_metadata_money_goods_conflict_skipped_when_already_money() -> None:
    """The conflict check is only for non-committing declared kinds.
    If declared_kind is already MONEY, the inviolable check above already handles it."""
    conflict = _metadata_money_goods_conflict(
        {"refund_amount_cents": 5000},
        declared_kind=CommitmentKind.MONEY,
    )
    assert conflict is None  # already handled by inviolable gate, not this check


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _policy_record(
    *,
    tenant_id: str,
    tools: dict[str, Any],
) -> TenantGovernancePolicyRecord:
    parameters = {"tools": tools}
    content_sha256 = canonical_sha256(
        {
            "tenant_id": tenant_id,
            "policy_type": ACTION_TOOLS_POLICY_TYPE,
            "parameters": parameters,
            "status": TenantGovernancePolicyStatus.ACTIVE.value,
            "version": 1,
            "approved_by": _APPROVED_BY,
            "effective_from": _NOW.isoformat(),
            "source_approval_id": _APPROVAL_ID,
        }
    )
    return TenantGovernancePolicyRecord(
        policy_id=derive_governance_policy_version_id(
            tenant_id=tenant_id,
            policy_type=ACTION_TOOLS_POLICY_TYPE,
            version=1,
        ),
        tenant_id=tenant_id,
        policy_type=ACTION_TOOLS_POLICY_TYPE,
        parameters=parameters,
        status=TenantGovernancePolicyStatus.ACTIVE,
        version=1,
        approved_by=_APPROVED_BY,
        effective_from=_NOW,
        created_at=_NOW,
        source_approval_id=_APPROVAL_ID,
        content_sha256=content_sha256,
        previous_version_sha256=None,
    )


class _DummyCredentialRuntime:
    """Minimal credential runtime stub for registry construction tests."""

    async def get_connector_configuration(
        self, *, tenant_id: str, tool_name: str
    ) -> None:
        return None
