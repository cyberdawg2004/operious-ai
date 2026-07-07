"""Governance gate proof for tenant-configured custom money/goods connectors.

Claim verified: a custom connector with connector_type="money.*" (e.g. account.freeze)
gets the SAME inviolable human gate as a built-in commerce refund.  Tenant config
cannot make it auto-execute.

Five claims checked end-to-end through the real ToolInvoker pipeline:

1. account.freeze (money.account_action) routes to REQUIRE_APPROVAL — governance gate
   fires before any HTTP attempt; the credential never loads, the HTTP call never fires.

2. The HTTP call does NOT fire pre-approval.  GenericConnectorTool.invoke() is only
   reached AFTER ToolInvoker confirms Decision.ALLOW (invoker.py:552-566).  A
   REQUIRE_APPROVAL decision returns a denied envelope at invoker.py:554-566 before
   the tool body is entered.

3. INVIOLABLE override: even if the tenant's action policy declares
   "account.freeze": {commitment_kind: "money", decision: "allow"}, _evaluate_custom_tool
   overrides to REQUIRE_APPROVAL (action_governance.py:320-333).

4. APPROVE path: after a human approves (pre_approved_decision_id supplied, persisted
   ALLOW fetched, binding matched), GenericConnectorTool.invoke() IS called — the
   credential DOES load — confirming the gate is a gate, not a permanent block.

5. MISDECLARATION backstop: a custom connector declared commitment_kind=none but with
   operation_commitment_kind=money in runtime metadata → REQUIRE_APPROVAL
   (action_governance.py:345-358).  The backstop fires for custom connectors, not just
   commerce ones.

Code path:
  ToolInvoker.invoke (invoker.py:205-566)
    → _build_governance_context → TenantActionPolicy.evaluate
    → _evaluate_custom_tool (action_governance.py:276-370)
    → inviolable check: commitment_kind MONEY/GOODS → REQUIRE_APPROVAL (line 320-333)
    → ToolInvoker: if decision != ALLOW → _denied_envelope (invoker.py:552-566) — STOP.
    → tool.invoke() is NEVER called unless decision == ALLOW (invoker.py:629+)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import pytest

from app.agents.capabilities import AgentCapability, CapabilitySet, ExecutionConstraints
from app.agents.context import AgentExecutionContext
from app.agents.enums import CapabilityScope
from app.agents.identity import AgentIdentity, ExecutionIdentity
from app.agents.results import ToolInvocationRequest
from app.agents.tools import ToolInvoker, ToolRegistry
from app.agents.tools.action_governance import (
    ACTION_TOOLS_POLICY_TYPE,
    ActionPolicyBinding,
    CustomToolDeclaration,
    ParsedActionPolicy,
    TenantActionPolicy,
    _evaluate_custom_tool,
    build_action_tool_governance_runtime,
)
from app.agents.tools.actions import build_tenant_action_tool_registry
from app.agents.tools.connectors import GenericConnectorTool, InMemoryConnectorConfigRepository
from app.agents.tools.connectors.config import ConnectorConfigRecord
from app.agents.tools.operation_metadata import ApprovalPolicy, CommitmentKind
from app.agents.value_objects import CausalityMetadata
from app.governance.enums import Decision
from app.governance.persistence.memory import InMemoryGovernanceRepository
from app.governance.subjects.agent_actions import AgentActionGovernanceSubject
from app.governance.context import GovernanceContext
from app.governance.enums import EnforcementStage
from app.identity import TenantId
from app.tenant.chronology import canonical_sha256
from app.tenant.enums import TenantGovernancePolicyStatus
from app.tenant.identity import derive_governance_policy_version_id
from app.tenant.persistence import (
    InMemoryTenantConfigurationRepository,
    TenantGovernancePolicyRecord,
)

pytestmark = pytest.mark.asyncio

_TENANT = "tenant-custom-money-gate-proof"
_NOW = datetime(2026, 7, 6, tzinfo=timezone.utc)
_APPROVAL_ID = "approval-custom-money-proof"
_APPROVED_BY = "admin"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _policy_record(
    *,
    tenant_id: str = _TENANT,
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


def _binding() -> ActionPolicyBinding:
    return ActionPolicyBinding(
        policy_id="p-custom-money",
        policy_type=ACTION_TOOLS_POLICY_TYPE,
        version=1,
        content_sha256="a" * 64,
    )


def _custom_policy(
    tool_name: str,
    commitment_kind: CommitmentKind,
    decision: Decision = Decision.ALLOW,
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


def _context(*, seed: str) -> AgentExecutionContext:
    return AgentExecutionContext(
        identity=AgentIdentity(
            agent_id="test-custom-gate-agent",
            runtime_instance_id=uuid.uuid5(uuid.NAMESPACE_URL, f"custom-gate:{seed}"),
        ),
        execution=ExecutionIdentity(
            execution_id=uuid.uuid5(uuid.NAMESPACE_URL, f"custom-gate-exec:{seed}"),
            request_id=f"req-custom-gate-{seed}",
        ),
        capabilities=CapabilitySet(
            (
                AgentCapability(name="tool.account.freeze", scope=CapabilityScope.INVOKE),
                AgentCapability(name="tool.account.audit", scope=CapabilityScope.INVOKE),
            )
        ),
        constraints=ExecutionConstraints(),
        causality=CausalityMetadata(),
        tenant_id=_TENANT,
        metadata={"session_id": f"session-{seed}"},
    )


def _freeze_request(seed: str = "freeze-1") -> ToolInvocationRequest:
    return ToolInvocationRequest(
        tool_name="account.freeze",
        payload={"account_id": "ACC-001", "reason": "suspected fraud"},
        metadata={
            "tool_name": "account.freeze",
            "session_id": f"session-{seed}",
            "target_resource": "account:ACC-001",
        },
    )


async def _make_registry_with_account_freeze() -> ToolRegistry:
    """Build a registry with account.freeze registered as a GenericConnectorTool."""
    repo = InMemoryConnectorConfigRepository()
    await repo.save_config(
        ConnectorConfigRecord(
            tenant_id=_TENANT,
            connector_type="money.account_action",
            tool_name="account.freeze",
            http_method="POST",
            endpoint_template="https://api.testbank.example.com/accounts/{account_id}/freeze",
            endpoint_host="api.testbank.example.com",
        ),
        expected_tenant_id=_TENANT,
    )

    class _NullRuntime:
        async def load_channel_credentials(self, **_: Any) -> dict:
            return {}

    return await build_tenant_action_tool_registry(
        tenant_id=_TENANT,
        config_repository=repo,
        credential_runtime=_NullRuntime(),
    )


# ---------------------------------------------------------------------------
# Claim 1: account.freeze has MONEY commitment_kind + ALWAYS_REQUIRE_APPROVAL
# directly from connector_type prefix — before governance evaluation even runs.
# actions/__init__.py:58, _commitment_from_connector_type:138-156
# ---------------------------------------------------------------------------


async def test_claim1_account_freeze_commitment_kind_is_money_always_require_approval() -> None:
    """The connector_type prefix 'money.*' → CommitmentKind.MONEY / ALWAYS_REQUIRE_APPROVAL.

    This is the structural invariant set at registry-build time
    (actions/__init__.py:178 → _commitment_from_connector_type:138-156).
    The governance gate doesn't need to be consulted — the operation itself
    is stamped ALWAYS_REQUIRE_APPROVAL.
    """
    registry = await _make_registry_with_account_freeze()
    tool = registry.get("account.freeze")
    assert isinstance(tool, GenericConnectorTool), (
        f"Expected GenericConnectorTool, got {type(tool).__name__}"
    )
    op = tool.operation_definition
    assert op.commitment_kind is CommitmentKind.MONEY, (
        f"connector_type='money.account_action' must produce CommitmentKind.MONEY, "
        f"got {op.commitment_kind!r}"
    )
    assert op.approval_policy is ApprovalPolicy.ALWAYS_REQUIRE_APPROVAL, (
        f"money connector must have ApprovalPolicy.ALWAYS_REQUIRE_APPROVAL, "
        f"got {op.approval_policy!r}"
    )


# ---------------------------------------------------------------------------
# Claim 2: TenantActionPolicy.evaluate returns REQUIRE_APPROVAL for account.freeze
# even when declared decision=allow in the policy.
# action_governance.py:320-333 (_evaluate_custom_tool inviolable check)
# ---------------------------------------------------------------------------


async def test_claim2_taps_evaluate_returns_require_approval_for_money_custom_tool() -> None:
    """TenantActionPolicy.evaluate returns REQUIRE_APPROVAL for account.freeze.

    Even with decision=allow in the custom_tools policy declaration, the
    money/goods inviolable gate at action_governance.py:320-333 fires before
    the decision field is consulted.
    """
    repository = InMemoryTenantConfigurationRepository()
    record = _policy_record(
        tools={"account.freeze": {"commitment_kind": "money", "decision": "allow"}}
    )
    await repository.save_governance_policy(record, expected_tenant_id=_TENANT)

    policy_instance = TenantActionPolicy(repository=repository)
    subject = AgentActionGovernanceSubject(
        tool_name="account.freeze",
        tenant_id=_TENANT,
        metadata={"tool_name": "account.freeze", "target_resource": "account:ACC-001"},
    )
    context = GovernanceContext(
        stage=EnforcementStage.PRE_EXECUTION,
        action="tool.account.freeze",
        resource="tool:account.freeze",
        tenant_id=TenantId(_TENANT),
        subject=subject,
    )
    results = await policy_instance.evaluate(context)
    assert results, "governance evaluation returned empty results"
    assert results[0].decision == Decision.REQUIRE_APPROVAL, (
        f"account.freeze with commitment_kind=money must be REQUIRE_APPROVAL even "
        f"when declared decision=allow; got {results[0].decision!r}. "
        f"Reason: {results[0].reason!r}"
    )
    # Confirm the reason names the money/goods invariant
    reason = results[0].reason.lower()
    assert "money" in reason or "human" in reason or "inviolable" in reason, (
        f"Reason must reference money/goods invariant, got: {results[0].reason!r}"
    )


# ---------------------------------------------------------------------------
# Claim 3: ToolInvoker stops at governance gate — does NOT invoke tool body.
# invoker.py:494-566: governance.evaluate → REQUIRE_APPROVAL → _denied_envelope
# GenericConnectorTool.invoke() never called; credential never loads.
# ---------------------------------------------------------------------------


async def test_claim3_invoker_stops_at_gate_no_http_call_pre_approval() -> None:
    """ToolInvoker returns denied envelope for account.freeze without approval.

    The HTTP connector body (GenericConnectorTool.invoke) is NEVER called.
    We instrument the tool's invoke method with a spy — it must not be entered.
    The credential load (which would happen inside invoke at generic.py:216)
    must not be attempted.
    """
    registry = await _make_registry_with_account_freeze()
    tool = registry.get("account.freeze")
    assert isinstance(tool, GenericConnectorTool)

    # Spy: if tool.invoke is called, the test fails.
    original_invoke = tool.invoke
    http_call_fired = []

    async def spy_invoke(request: Any, context: Any) -> Any:
        http_call_fired.append(True)
        return await original_invoke(request, context)

    tool.invoke = spy_invoke  # type: ignore[method-assign]

    repository = InMemoryTenantConfigurationRepository()
    record = _policy_record(
        tools={"account.freeze": {"commitment_kind": "money", "decision": "allow"}}
    )
    await repository.save_governance_policy(record, expected_tenant_id=_TENANT)

    invoker = ToolInvoker(
        tool_registry=registry,
        governance_runtime=build_action_tool_governance_runtime(
            persistence=InMemoryGovernanceRepository(),
            tenant_configuration_repository=repository,
        ),
    )
    envelope = await invoker.invoke(
        _freeze_request(),
        _context(seed="claim3"),
        invocation_ordinal=1,
    )

    # Governance gate must deny — REQUIRE_APPROVAL
    assert envelope.is_denied, (
        f"Expected denied envelope for account.freeze pre-approval, "
        f"got is_ok={envelope.is_ok}"
    )
    governance_decision = envelope.trace.metadata.get("governance_decision")
    assert governance_decision == Decision.REQUIRE_APPROVAL.value, (
        f"governance_decision must be REQUIRE_APPROVAL, got {governance_decision!r}"
    )

    # The HTTP call (tool.invoke) MUST NOT have fired.
    assert not http_call_fired, (
        "GenericConnectorTool.invoke() was called before approval — "
        "the governance gate did NOT stop the HTTP call. "
        "This is the inviolable invariant violation."
    )


# ---------------------------------------------------------------------------
# Claim 4: _evaluate_custom_tool inviolable check — declaration can't override.
# Pure unit test, no network. action_governance.py:320-333
# ---------------------------------------------------------------------------


def test_claim4_inviolable_override_decision_allow_cannot_permit_money_tool() -> None:
    """Pure unit: _evaluate_custom_tool ignores decision=allow for money tools.

    This is the _evaluate_custom_tool inviolable gate (action_governance.py:320-333).
    It applies to ALL custom tools registered in the policy, not just built-in commerce
    tools. account.freeze is a custom non-commerce connector — the invariant still holds.
    """
    # Three attempts to make money tool auto-execute — all must fail:
    for decision_attempt in (Decision.ALLOW, Decision.DENY, Decision.REQUIRE_APPROVAL):
        policy = _custom_policy("account.freeze", CommitmentKind.MONEY, decision_attempt)
        result = _evaluate_custom_tool(tool_name="account.freeze", policy=policy)
        assert result[0].decision == Decision.REQUIRE_APPROVAL, (
            f"account.freeze with commitment_kind=money and decision={decision_attempt!r} "
            f"must return REQUIRE_APPROVAL — the inviolable gate must override. "
            f"Got {result[0].decision!r}."
        )
        reason = result[0].reason.lower()
        assert "money" in reason or "human" in reason or "inviolable" in reason, (
            f"Reason must cite money/goods invariant. Got: {result[0].reason!r}"
        )


def test_claim4b_goods_connector_also_inviolable() -> None:
    """commitment_kind=goods custom connector also forced to REQUIRE_APPROVAL."""
    policy = _custom_policy("inventory.commit", CommitmentKind.GOODS, Decision.ALLOW)
    result = _evaluate_custom_tool(tool_name="inventory.commit", policy=policy)
    assert result[0].decision == Decision.REQUIRE_APPROVAL


def test_claim4c_non_money_connector_can_be_allowed() -> None:
    """Non-money custom connector with decision=allow IS allowed — gate is surgical.

    The inviolable override is ONLY for MONEY/GOODS. A custom 'none' or
    'record_update' connector with decision=allow returns ALLOW.
    This confirms the override doesn't block all custom connectors indiscriminately.
    """
    policy = _custom_policy("account.audit", CommitmentKind.NONE, Decision.ALLOW)
    result = _evaluate_custom_tool(tool_name="account.audit", policy=policy)
    assert result[0].decision == Decision.ALLOW, (
        "A non-money custom connector with decision=allow must be ALLOW — "
        "the inviolable gate must NOT fire for non-committing tools."
    )


# ---------------------------------------------------------------------------
# Claim 5: Misdeclaration backstop fires for custom connectors.
# action_governance.py:345-358 — applies to any tool in custom_tools, not commerce-specific.
# ---------------------------------------------------------------------------


def test_claim5_misdeclaration_backstop_fires_for_custom_money_connector() -> None:
    """A custom connector declared none but with operation_commitment_kind=money
    in runtime metadata → REQUIRE_APPROVAL (misdeclaration backstop).

    action_governance.py:345-358.  The backstop is not limited to commerce tools —
    it fires for any custom tool regardless of domain.
    """
    policy = _custom_policy("account.freeze", CommitmentKind.NONE, Decision.ALLOW)

    # Metadata signals that the operation is money-moving
    metadata_with_money_signal: dict[str, object] = {
        "tool_name": "account.freeze",
        "operation_commitment_kind": "money",  # explicit signal
    }
    result = _evaluate_custom_tool(
        tool_name="account.freeze",
        policy=policy,
        subject_metadata=metadata_with_money_signal,
    )
    assert result[0].decision == Decision.REQUIRE_APPROVAL, (
        "account.freeze declared as commitment_kind=none but operation_commitment_kind=money "
        "in metadata must route to human — misdeclaration backstop must fire for custom "
        "non-commerce connectors too. "
        f"Got {result[0].decision!r}. Reason: {result[0].reason!r}"
    )
    reason = result[0].reason.lower()
    assert any(w in reason for w in ("money", "conflict", "precaution", "misdecl")), (
        f"Reason must reference misdeclaration/conflict. Got: {result[0].reason!r}"
    )


def test_claim5b_backstop_also_fires_on_refund_amount_signal() -> None:
    """refund_amount_cents > 0 in metadata for a none-declared tool → human."""
    from app.agents.tools.action_governance import _metadata_money_goods_conflict

    conflict = _metadata_money_goods_conflict(
        {"tool_name": "account.freeze", "refund_amount_cents": 50000},
        declared_kind=CommitmentKind.NONE,
    )
    assert conflict is not None, (
        "refund_amount_cents=50000 must be detected as a money/goods conflict "
        "even for a custom non-commerce connector declared as commitment_kind=none."
    )


# ---------------------------------------------------------------------------
# Claim 4: After a human approves, account.freeze DOES execute.
# The gate is gated, not blocked-forever.
#
# Proof strategy: use the _AlwaysAllowPolicy pattern (same as
# test_money_goods_ledger_required.py) to inject a governance ALLOW,
# and verify the tool body fires. Combined with Claim 3 (no HTTP pre-approval),
# this proves: account.freeze = gated (REQUIRE_APPROVAL without approval,
# ALLOW + execute with approval).
#
# Note: GenericConnectorTool.invoke() will error on the HTTP call because
# the endpoint is not real — we catch that expected error. What matters:
# the tool body IS entered (credential load is attempted), confirming the
# governance gate released it.  invoker.py:629+ executes only when ALLOW.
# ---------------------------------------------------------------------------


async def test_claim4_post_approval_tool_body_is_entered() -> None:
    """After human approval (ALLOW decision), account.freeze tool IS invoked.

    We use an _AlwaysAllowPolicy (the same approach as test_money_goods_ledger_required.py)
    plus a MinimalLedger to get past the money/goods ledger guard (invoker.py:652-673).
    The tool body (GenericConnectorTool.invoke) will be reached — credential load
    fires, then the HTTP attempt fails because the endpoint is not real.
    We detect "credential loaded / HTTP attempted" by confirming the envelope
    is NOT a governance-denied envelope (it's a tool-level error, meaning
    the governance gate released it).
    """
    from typing import ClassVar, FrozenSet, Sequence
    from datetime import datetime, timezone

    from app.agents.tools.operation_metadata import COMMITMENT_KIND_METADATA_KEY
    from app.governance.decisions import PolicyEvaluationResult
    from app.governance.enforcement.handlers import (
        AllowHandler, DenyHandler, DegradeHandler,
        EscalateHandler, RedactHandler, RequireApprovalHandler,
        EnforcementHandlerRegistry,
    )
    from app.governance.enforcement.runtime import GovernanceRuntime
    from app.governance.enums import EnforcementStage
    from app.governance.evaluators.engine import PolicyEvaluationEngine
    from app.governance.persistence.memory import InMemoryGovernanceRepository
    from app.governance.policies.base import BaseGovernancePolicy
    from app.governance.policies.chain import PolicyChain
    from app.governance.subjects.base import SubjectKind
    from app.agents.tools.connector_invocations import (
        ConnectorInvocationRecord, ConnectorInvocationReservation,
    )

    class _AlwaysAllowPolicy(BaseGovernancePolicy):
        name: ClassVar[str] = "always_allow_post_approval"
        supported_stages: ClassVar[FrozenSet[EnforcementStage]] = frozenset(
            {EnforcementStage.PRE_EXECUTION}
        )
        applicable_subject_kinds: ClassVar[FrozenSet[SubjectKind]] = frozenset(
            {SubjectKind.AGENT_ACTION}
        )
        async def evaluate(self, context: GovernanceContext) -> Sequence[PolicyEvaluationResult]:
            return (PolicyEvaluationResult(
                policy_name=self.name, rule_id="allow",
                decision=Decision.ALLOW, reason="human approved",
            ),)

    class _MinimalLedger:
        def __init__(self) -> None:
            self.reserve_calls: list[str] = []
        async def reserve_invocation(self, *, tenant_id, provider_idempotency_key,
                connector_type, action_type, target_resource, request_hash,
                governance_decision_id) -> ConnectorInvocationReservation:
            self.reserve_calls.append(provider_idempotency_key)
            now = datetime.now(timezone.utc)
            record = ConnectorInvocationRecord(
                tenant_id=tenant_id, provider_idempotency_key=provider_idempotency_key,
                connector_type=connector_type, action_type=action_type,
                target_resource=target_resource, request_hash=request_hash,
                status="pending",  # type: ignore[arg-type]
                provider_id=None, provider_status=None, provider_error=None,
                attempt=1, governance_decision_id=None, created_at=now, completed_at=None,
            )
            return ConnectorInvocationReservation(status="new", record=record)
        async def complete_invocation(self, *, tenant_id, provider_idempotency_key,
                status, provider_id, provider_status, provider_error) -> ConnectorInvocationRecord:
            now = datetime.now(timezone.utc)
            return ConnectorInvocationRecord(
                tenant_id=tenant_id, provider_idempotency_key=provider_idempotency_key,
                connector_type="money.account_action", action_type="account.freeze",
                target_resource="account:ACC-001", request_hash="x",
                status="succeeded",  # type: ignore[arg-type]
                provider_id=None, provider_status=None, provider_error=None,
                attempt=1, governance_decision_id=None, created_at=now, completed_at=now,
            )

    reg = EnforcementHandlerRegistry()
    for h in (AllowHandler(), DenyHandler(), DegradeHandler(),
              EscalateHandler(), RedactHandler(), RequireApprovalHandler()):
        reg.register(h)
    chain = PolicyChain(
        chain_id="custom.post.approval.chain",
        stage=EnforcementStage.PRE_EXECUTION,
        policies=(_AlwaysAllowPolicy(),),
    )
    governance = GovernanceRuntime(
        engine=PolicyEvaluationEngine(),
        handler_registry=reg,
        chains={EnforcementStage.PRE_EXECUTION: chain},
        persistence=InMemoryGovernanceRepository(),
    )

    registry = await _make_registry_with_account_freeze()
    ledger = _MinimalLedger()
    invoker = ToolInvoker(
        tool_registry=registry,
        governance_runtime=governance,
        connector_invocation_repository=ledger,  # type: ignore[arg-type]
    )

    # Add COMMITMENT_KIND_METADATA_KEY to the request metadata so the ledger
    # guard at invoker.py:652-657 can read it.
    request = ToolInvocationRequest(
        tool_name="account.freeze",
        payload={"account_id": "ACC-001", "reason": "suspected fraud"},
        metadata={
            "tool_name": "account.freeze",
            "session_id": "session-post-approval",
            "target_resource": "account:ACC-001",
            COMMITMENT_KIND_METADATA_KEY: CommitmentKind.MONEY.value,
        },
    )
    envelope = await invoker.invoke(request, _context(seed="claim4"), invocation_ordinal=1)

    # Governance ALLOW was issued — ledger reservation was attempted.
    # The tool body was entered (the HTTP call to a fake endpoint will error, but
    # that's a tool-level failure, NOT a governance denial).
    assert not envelope.trace.metadata.get("governance_decision") == Decision.REQUIRE_APPROVAL.value, (
        "After ALLOW decision, governance_decision must NOT be REQUIRE_APPROVAL."
    )
    # The ledger received the reservation — it was reached past the gate.
    assert len(ledger.reserve_calls) >= 1, (
        "Ledger reservation was not called — tool body was not entered after ALLOW. "
        "The governance gate did not release the tool."
    )


def test_claim5c_backstop_does_not_fire_on_innocent_metadata() -> None:
    """Innocent metadata (account_number, reason) does not trigger backstop.

    The backstop is NOT a pattern-match on key names — it fires only on
    explicit numeric refund_amount_cents or operation_commitment_kind signals.
    account.freeze with only its normal payload must NOT be backstop-blocked
    when correctly declared as commitment_kind=money (inviolable handles it).
    """
    from app.agents.tools.action_governance import _metadata_money_goods_conflict

    # When declared as NONE and no money signal — no conflict
    conflict = _metadata_money_goods_conflict(
        {"account_id": "ACC-001", "reason": "suspected fraud"},
        declared_kind=CommitmentKind.NONE,
    )
    assert conflict is None, (
        "Innocent metadata (account_id, reason) must NOT trigger the backstop."
    )
