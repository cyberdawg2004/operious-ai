"""C-2: Seeded-replay path must enforce binding HMAC and TTL expiry.

Before this fix the seeded-replay path (invoker.py) only checked
decision==ALLOW.  A persisted ALLOW decision could be replayed with a
tampered binding or after TTL expiry with no rejection.

The seeded path is an internal same-session optimization: when the
governance engine already evaluated a decision for this exact invocation
(deterministic from execution context), a re-invocation should reuse it
rather than re-running governance.  The decision ID is derived from the
compound seed ``_action_governance_decision_seed()``, not from anything
user-controllable.

Grant consumption is NOT required on the seeded path — seeded decisions
are auto-allow governance decisions, not human-manager approvals; no grant
is issued for them.

Strategy: build the governance context the invoker would build (using the
exported private helpers), derive the canonical seeded decision ID, and
pre-seed the repository with a decision whose binding is wrong or whose
timestamp is stale.  Then invoke — the seeded path finds the pre-stored
record and must reject before the tool body fires.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import ClassVar, FrozenSet, Sequence

import pytest

from app.agents.capabilities import AgentCapability, CapabilitySet, ExecutionConstraints
from app.agents.context import AgentExecutionContext
from app.agents.enums import CapabilityScope
from app.agents.identity import AgentIdentity, ExecutionIdentity
from app.agents.results import ToolInvocationRequest, ToolInvocationResult
from app.agents.tools import BaseTool, ToolCapability, ToolInvoker, ToolRegistry
from app.agents.tools.invoker import (
    AGENT_ACTION_BINDING_KEY,
    _action_governance_decision_seed,  # private but importable
    _build_governance_context,  # private but importable
    _seeded_governance_decision_id,  # private but importable
    compute_agent_action_binding,
)
from app.agents.value_objects import CausalityMetadata
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
from app.governance.identity.decision_ids import derive_decision_id
from app.governance.persistence.memory import InMemoryGovernanceRepository
from app.governance.persistence.records import GovernanceDecisionRecord
from app.governance.policies.base import BaseGovernancePolicy
from app.governance.policies.chain import PolicyChain
from app.governance.subjects.base import SubjectKind

pytestmark = pytest.mark.asyncio

_TENANT = "tenant-seeded-replay"
_TOOL_NAME = "mutating_seeded_action"
_PAYLOAD: dict[str, object] = {"order_id": "ORD-C2"}
_EXECUTION_ID = uuid.uuid5(uuid.NAMESPACE_URL, "seeded-replay-c2-execution")


class _AlwaysAllowPolicy(BaseGovernancePolicy):
    name: ClassVar[str] = "seeded_replay_test_allow"
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
    name: ClassVar[str] = _TOOL_NAME
    capability: ClassVar[ToolCapability] = ToolCapability.ACTION
    required_capabilities: ClassVar[frozenset[str]] = frozenset({"tool.mutate"})

    def __init__(self) -> None:
        self.call_count = 0

    async def invoke(
        self, request: ToolInvocationRequest, context: AgentExecutionContext
    ) -> ToolInvocationResult:
        self.call_count += 1
        return ToolInvocationResult(output={"ok": True})


def _make_registry(tool: BaseTool) -> ToolRegistry:
    r = ToolRegistry()
    r.register(tool)
    return r


def _make_handlers() -> EnforcementHandlerRegistry:
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
    return reg


def _make_governance(persistence: InMemoryGovernanceRepository) -> GovernanceRuntime:
    chain = PolicyChain(
        chain_id="test.seeded.c2.chain",
        stage=EnforcementStage.PRE_EXECUTION,
        policies=(_AlwaysAllowPolicy(),),
    )
    return GovernanceRuntime(
        engine=PolicyEvaluationEngine(),
        handler_registry=_make_handlers(),
        chains={EnforcementStage.PRE_EXECUTION: chain},
        persistence=persistence,
    )


def _make_context() -> AgentExecutionContext:
    return AgentExecutionContext(
        identity=AgentIdentity(
            agent_id="test-agent-c2",
            runtime_instance_id=uuid.uuid5(uuid.NAMESPACE_URL, "seeded-rt-c2"),
        ),
        execution=ExecutionIdentity(
            execution_id=_EXECUTION_ID,
            request_id="req-seeded-c2",
        ),
        capabilities=CapabilitySet(
            (AgentCapability(name="tool.mutate", scope=CapabilityScope.INVOKE),)
        ),
        constraints=ExecutionConstraints(),
        causality=CausalityMetadata(),
        tenant_id=_TENANT,
    )


def _make_request() -> ToolInvocationRequest:
    return ToolInvocationRequest(
        tool_name=_TOOL_NAME,
        payload=_PAYLOAD,
        metadata={"target_resource": "order:ORD-C2"},
    )


def _derive_seeded_decision_id(
    request: ToolInvocationRequest,
    ctx: AgentExecutionContext,
    tool: BaseTool,
) -> uuid.UUID:
    """Derive the canonical seeded decision ID the invoker would use."""
    gc = _build_governance_context(request, ctx, tool)
    decision_id = _seeded_governance_decision_id(gc.metadata)
    assert decision_id is not None, "test tool must be ACTION-capable"
    return decision_id


def _canonical_binding(
    request: ToolInvocationRequest, ctx: AgentExecutionContext
) -> str:
    return compute_agent_action_binding(
        tenant_id=ctx.tenant_id or "",
        tool_name=request.tool_name,
        actor=f"agent:{ctx.identity.agent_id}",
        payload=request.payload,
    )


def _stored_decision(
    *,
    decision_id: str,
    binding: str,
    decided_at: datetime | None = None,
) -> GovernanceDecisionRecord:
    return GovernanceDecisionRecord(
        decision_id=decision_id,
        decision=Decision.ALLOW.value,
        stage=EnforcementStage.PRE_EXECUTION.value,
        policy_chain_id="test.seeded.c2.chain",
        reason="seeded allow",
        decided_at=(decided_at or datetime.now(timezone.utc)).isoformat(),
        tenant_id=_TENANT,
        subject_kind="agent_action",
        metadata={AGENT_ACTION_BINDING_KEY: binding},
    )


# ─── Happy path ───────────────────────────────────────────────────────────────


async def test_seeded_replay_valid_binding_and_fresh_decision_executes() -> None:
    """Happy path: pre-stored ALLOW with correct binding + fresh TTL → tool fires."""
    tool = _ActionTool()
    request = _make_request()
    ctx = _make_context()
    decision_id = str(_derive_seeded_decision_id(request, ctx, tool))
    binding = _canonical_binding(request, ctx)

    persistence = InMemoryGovernanceRepository()
    await persistence.record_decision(
        _stored_decision(decision_id=decision_id, binding=binding)
    )

    invoker = ToolInvoker(
        tool_registry=_make_registry(tool),
        governance_runtime=_make_governance(persistence),
    )
    envelope = await invoker.invoke(request, ctx, invocation_ordinal=1)
    assert tool.call_count == 1, f"expected 1 call, got {tool.call_count}"
    assert envelope.result is not None


# ─── Binding mismatch ─────────────────────────────────────────────────────────


async def test_seeded_replay_binding_mismatch_is_rejected() -> None:
    """Pre-stored ALLOW with a tampered binding must be denied before tool fires."""
    tool = _ActionTool()
    request = _make_request()
    ctx = _make_context()
    decision_id = str(_derive_seeded_decision_id(request, ctx, tool))

    # Store a binding computed for a DIFFERENT payload — simulates a
    # decision persisted for one tool invocation being replayed against a
    # different payload (parameter injection attack).
    wrong_binding = compute_agent_action_binding(
        tenant_id=_TENANT,
        tool_name=_TOOL_NAME,
        actor="agent:test-agent-c2",
        payload={"order_id": "DIFFERENT-ORDER"},
    )

    persistence = InMemoryGovernanceRepository()
    await persistence.record_decision(
        _stored_decision(decision_id=decision_id, binding=wrong_binding)
    )

    invoker = ToolInvoker(
        tool_registry=_make_registry(tool),
        governance_runtime=_make_governance(persistence),
    )
    envelope = await invoker.invoke(request, ctx, invocation_ordinal=1)
    assert tool.call_count == 0, "tool must not fire on binding mismatch"
    assert envelope.result is None
    assert "binding_mismatch" in str(envelope.trace.metadata.get("reason") or ""), (
        f"expected binding_mismatch in reason, got: {envelope.trace.metadata.get('reason')!r}"
    )


async def test_seeded_replay_missing_binding_is_rejected() -> None:
    """Pre-stored ALLOW with no AGENT_ACTION_BINDING_KEY in metadata → denied."""
    tool = _ActionTool()
    request = _make_request()
    ctx = _make_context()
    decision_id = str(_derive_seeded_decision_id(request, ctx, tool))

    no_binding_decision = GovernanceDecisionRecord(
        decision_id=decision_id,
        decision=Decision.ALLOW.value,
        stage=EnforcementStage.PRE_EXECUTION.value,
        policy_chain_id="test.seeded.c2.chain",
        reason="allow no binding",
        decided_at=datetime.now(timezone.utc).isoformat(),
        tenant_id=_TENANT,
        subject_kind="agent_action",
        metadata={},  # deliberately no AGENT_ACTION_BINDING_KEY
    )

    persistence = InMemoryGovernanceRepository()
    await persistence.record_decision(no_binding_decision)

    invoker = ToolInvoker(
        tool_registry=_make_registry(tool),
        governance_runtime=_make_governance(persistence),
    )
    envelope = await invoker.invoke(request, ctx, invocation_ordinal=1)
    assert tool.call_count == 0, "tool must not fire when binding is absent"
    assert "binding_mismatch" in str(envelope.trace.metadata.get("reason") or "")


# ─── TTL expiry ───────────────────────────────────────────────────────────────


async def test_seeded_replay_expired_decision_is_rejected() -> None:
    """Pre-stored ALLOW older than the TTL must be denied — stale replays blocked."""
    tool = _ActionTool()
    request = _make_request()
    ctx = _make_context()
    decision_id = str(_derive_seeded_decision_id(request, ctx, tool))
    binding = _canonical_binding(request, ctx)

    stale_at = datetime.now(timezone.utc) - timedelta(hours=2)

    persistence = InMemoryGovernanceRepository()
    await persistence.record_decision(
        _stored_decision(decision_id=decision_id, binding=binding, decided_at=stale_at)
    )

    invoker = ToolInvoker(
        tool_registry=_make_registry(tool),
        governance_runtime=_make_governance(persistence),
    )
    envelope = await invoker.invoke(request, ctx, invocation_ordinal=1)
    assert tool.call_count == 0, "tool must not fire on expired seeded decision"
    assert envelope.result is None
    assert "expired" in str(envelope.trace.metadata.get("reason") or ""), (
        f"expected expired in reason, got: {envelope.trace.metadata.get('reason')!r}"
    )


# ─── Regression: non-ALLOW still rejected ────────────────────────────────────


async def test_seeded_replay_deny_decision_is_rejected() -> None:
    """Pre-stored DENY must still be rejected (pre-existing check, regression guard)."""
    tool = _ActionTool()
    request = _make_request()
    ctx = _make_context()
    decision_id = str(_derive_seeded_decision_id(request, ctx, tool))
    binding = _canonical_binding(request, ctx)

    deny_decision = GovernanceDecisionRecord(
        decision_id=decision_id,
        decision=Decision.DENY.value,
        stage=EnforcementStage.PRE_EXECUTION.value,
        policy_chain_id="test.seeded.c2.chain",
        reason="test deny",
        decided_at=datetime.now(timezone.utc).isoformat(),
        tenant_id=_TENANT,
        subject_kind="agent_action",
        metadata={AGENT_ACTION_BINDING_KEY: binding},
    )

    persistence = InMemoryGovernanceRepository()
    await persistence.record_decision(deny_decision)

    invoker = ToolInvoker(
        tool_registry=_make_registry(tool),
        governance_runtime=_make_governance(persistence),
    )
    envelope = await invoker.invoke(request, ctx, invocation_ordinal=1)
    assert tool.call_count == 0
