"""Finding 12 / C-2 edge: MONEY/GOODS actions must fail closed without ledger.

A money/goods action (commitment_kind == MONEY or GOODS) must NOT execute
when connector_invocation_repository is None — the ledger is the one-shot
double-fire guard, and executing without it allows double-execution within
the TTL window.

Scope:
  - MONEY/GOODS action + no ledger → failed envelope, tool body never called.
  - MONEY/GOODS action + ledger present → executes normally (one-shot preserved).
  - NONE/RECORD_UPDATE action + no ledger → proceeds (informational, no double-fire risk).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import ClassVar, FrozenSet, Sequence

import pytest

from app.agents.capabilities import AgentCapability, CapabilitySet, ExecutionConstraints
from app.agents.context import AgentExecutionContext
from app.agents.enums import CapabilityScope
from app.agents.identity import AgentIdentity, ExecutionIdentity
from app.agents.results import ToolInvocationRequest, ToolInvocationResult
from app.agents.tools import BaseTool, ToolCapability, ToolInvoker, ToolRegistry
from app.agents.value_objects import CausalityMetadata
from app.agents.tools.operation_metadata import (
    COMMITMENT_KIND_METADATA_KEY,
    CommitmentKind,
)
from app.governance.context import GovernanceContext
from app.governance.decisions import PolicyEvaluationResult
from app.governance.enforcement.handlers import (
    AllowHandler,
    DegradeHandler,
    DenyHandler,
    EnforcementHandlerRegistry,
    EscalateHandler,
    RedactHandler,
    RequireApprovalHandler,
)
from app.governance.enforcement.runtime import GovernanceRuntime
from app.governance.enums import Decision, EnforcementStage
from app.governance.evaluators.engine import PolicyEvaluationEngine
from app.governance.persistence.memory import InMemoryGovernanceRepository
from app.governance.policies.base import BaseGovernancePolicy
from app.governance.policies.chain import PolicyChain
from app.governance.subjects.base import SubjectKind
from app.agents.tools.connector_invocations import (
    ConnectorInvocationRecord,
    ConnectorInvocationReservation,
)

pytestmark = pytest.mark.asyncio

_TENANT = "tenant-ledger-guard"
_EXECUTION_ID = uuid.uuid5(uuid.NAMESPACE_URL, "ledger-guard-execution")


# ─── Minimal fixtures ─────────────────────────────────────────────────────────


class _AlwaysAllowPolicy(BaseGovernancePolicy):
    name: ClassVar[str] = "ledger_guard_test_allow"
    supported_stages: ClassVar[FrozenSet[EnforcementStage]] = frozenset(
        {EnforcementStage.PRE_EXECUTION}
    )
    applicable_subject_kinds: ClassVar[FrozenSet[SubjectKind]] = frozenset(
        {SubjectKind.AGENT_ACTION}
    )

    async def evaluate(
        self, context: GovernanceContext
    ) -> Sequence[PolicyEvaluationResult]:
        return (
            PolicyEvaluationResult(
                policy_name=self.name,
                rule_id="allow",
                decision=Decision.ALLOW,
                reason="test fixture",
            ),
        )


class _ActionTool(BaseTool):
    name: ClassVar[str] = "money_action"
    capability: ClassVar[ToolCapability] = ToolCapability.ACTION
    required_capabilities: ClassVar[frozenset[str]] = frozenset({"tool.mutate"})

    def __init__(self) -> None:
        self.call_count = 0

    async def invoke(
        self, request: ToolInvocationRequest, context: AgentExecutionContext
    ) -> ToolInvocationResult:
        self.call_count += 1
        return ToolInvocationResult(output={"ok": True})


class _NonCommittingTool(BaseTool):
    name: ClassVar[str] = "record_update_action"
    capability: ClassVar[ToolCapability] = ToolCapability.ACTION
    required_capabilities: ClassVar[frozenset[str]] = frozenset({"tool.mutate"})

    def __init__(self) -> None:
        self.call_count = 0

    async def invoke(
        self, request: ToolInvocationRequest, context: AgentExecutionContext
    ) -> ToolInvocationResult:
        self.call_count += 1
        return ToolInvocationResult(output={"ok": True})


class _MinimalLedger:
    """Stub ledger that always accepts the reservation (status='new')."""

    def __init__(self) -> None:
        self.reserve_calls: list[str] = []

    async def reserve_invocation(
        self,
        *,
        tenant_id: str,
        provider_idempotency_key: str,
        connector_type: str,
        action_type: str,
        target_resource: str,
        request_hash: str,
        governance_decision_id: object,
    ) -> ConnectorInvocationReservation:
        self.reserve_calls.append(provider_idempotency_key)
        now = datetime.now(timezone.utc)
        record = ConnectorInvocationRecord(
            tenant_id=tenant_id,
            provider_idempotency_key=provider_idempotency_key,
            connector_type=connector_type,
            action_type=action_type,
            target_resource=target_resource,
            request_hash=request_hash,
            status="pending",  # type: ignore[arg-type]
            provider_id=None,
            provider_status=None,
            provider_error=None,
            attempt=1,
            governance_decision_id=None,
            created_at=now,
            completed_at=None,
        )
        return ConnectorInvocationReservation(status="new", record=record)

    async def complete_invocation(
        self,
        *,
        tenant_id: str,
        provider_idempotency_key: str,
        status: object,
        provider_id: object,
        provider_status: object,
        provider_error: object,
    ) -> ConnectorInvocationRecord:
        now = datetime.now(timezone.utc)
        return ConnectorInvocationRecord(
            tenant_id=tenant_id,
            provider_idempotency_key=provider_idempotency_key,
            connector_type="money_action",
            action_type="money_action",
            target_resource="test",
            request_hash="x",
            status="succeeded",  # type: ignore[arg-type]
            provider_id=None,
            provider_status=None,
            provider_error=None,
            attempt=1,
            governance_decision_id=None,
            created_at=now,
            completed_at=now,
        )


def _make_governance(
    persistence: InMemoryGovernanceRepository | None = None,
) -> GovernanceRuntime:
    reg = EnforcementHandlerRegistry()
    for h in (
        AllowHandler(),
        DenyHandler(),
        DegradeHandler(),
        EscalateHandler(),
        RedactHandler(),
        RequireApprovalHandler(),
    ):
        reg.register(h)
    chain = PolicyChain(
        chain_id="ledger.guard.test.chain",
        stage=EnforcementStage.PRE_EXECUTION,
        policies=(_AlwaysAllowPolicy(),),
    )
    return GovernanceRuntime(
        engine=PolicyEvaluationEngine(),
        handler_registry=reg,
        chains={EnforcementStage.PRE_EXECUTION: chain},
        persistence=persistence or InMemoryGovernanceRepository(),
    )


def _make_context() -> AgentExecutionContext:
    return AgentExecutionContext(
        identity=AgentIdentity(
            agent_id="test-agent",
            runtime_instance_id=uuid.uuid5(uuid.NAMESPACE_URL, "ledger-rt"),
        ),
        execution=ExecutionIdentity(
            execution_id=_EXECUTION_ID,
            request_id="req-ledger",
        ),
        capabilities=CapabilitySet(
            (AgentCapability(name="tool.mutate", scope=CapabilityScope.INVOKE),)
        ),
        constraints=ExecutionConstraints(),
        causality=CausalityMetadata(),
        tenant_id=_TENANT,
    )


def _make_registry(tool: BaseTool) -> ToolRegistry:
    r = ToolRegistry()
    r.register(tool)
    return r


# ─── Tests ────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "commitment_kind",
    [CommitmentKind.MONEY.value, CommitmentKind.GOODS.value],
)
async def test_money_goods_action_fails_closed_without_ledger(
    commitment_kind: str,
) -> None:
    """MONEY/GOODS action with no connector ledger → failed envelope, tool never fires."""
    tool = _ActionTool()
    invoker = ToolInvoker(
        tool_registry=_make_registry(tool),
        governance_runtime=_make_governance(),
        connector_invocation_repository=None,  # ← no ledger
    )
    request = ToolInvocationRequest(
        tool_name=_ActionTool.name,
        payload={"order_id": "ORD-001"},
        metadata={
            "target_resource": "order:ORD-001",
            COMMITMENT_KIND_METADATA_KEY: commitment_kind,
        },
    )
    envelope = await invoker.invoke(request, _make_context(), invocation_ordinal=1)

    assert tool.call_count == 0, (
        f"tool must not fire for {commitment_kind!r} action without ledger; "
        f"call_count={tool.call_count}"
    )
    assert envelope.result is None
    assert "money_goods_action_requires_ledger" in str(
        envelope.trace.metadata.get("reason") or ""
    ), f"expected ledger-required reason, got: {envelope.trace.metadata.get('reason')!r}"


async def test_money_goods_action_executes_with_ledger() -> None:
    """MONEY/GOODS action with a ledger present → executes normally."""
    tool = _ActionTool()
    ledger = _MinimalLedger()
    invoker = ToolInvoker(
        tool_registry=_make_registry(tool),
        governance_runtime=_make_governance(),
        connector_invocation_repository=ledger,  # type: ignore[arg-type]
    )
    request = ToolInvocationRequest(
        tool_name=_ActionTool.name,
        payload={"order_id": "ORD-002"},
        metadata={
            "target_resource": "order:ORD-002",
            COMMITMENT_KIND_METADATA_KEY: CommitmentKind.GOODS.value,
        },
    )
    envelope = await invoker.invoke(request, _make_context(), invocation_ordinal=1)

    assert tool.call_count == 1, (
        f"tool must fire exactly once with ledger present; call_count={tool.call_count}"
    )
    assert envelope.result is not None


@pytest.mark.parametrize(
    "commitment_kind",
    [CommitmentKind.NONE.value, CommitmentKind.RECORD_UPDATE.value],
)
async def test_non_committing_action_proceeds_without_ledger(
    commitment_kind: str,
) -> None:
    """NONE/RECORD_UPDATE actions may proceed without the ledger (no double-fire risk)."""
    tool = _NonCommittingTool()
    invoker = ToolInvoker(
        tool_registry=_make_registry(tool),
        governance_runtime=_make_governance(),
        connector_invocation_repository=None,  # ← no ledger, should be fine
    )
    request = ToolInvocationRequest(
        tool_name=_NonCommittingTool.name,
        payload={"record_id": "REC-001"},
        metadata={
            "target_resource": "record:REC-001",
            COMMITMENT_KIND_METADATA_KEY: commitment_kind,
        },
    )
    envelope = await invoker.invoke(request, _make_context(), invocation_ordinal=1)

    assert tool.call_count == 1, (
        f"non-committing tool must fire for {commitment_kind!r} without ledger; "
        f"call_count={tool.call_count}"
    )
    assert envelope.result is not None
