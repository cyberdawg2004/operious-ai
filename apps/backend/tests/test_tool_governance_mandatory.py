"""PR_RT-SAFE-2 mandatory governance for action-capable tools."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import ClassVar, FrozenSet, Sequence

import pytest

from app.agents.capabilities import (
    AgentCapability,
    CapabilitySet,
    ExecutionConstraints,
)
from app.agents.context import AgentExecutionContext
from app.agents.enums import CapabilityScope
from app.agents.exceptions import ToolConfigurationError
from app.agents.identity import AgentIdentity, ExecutionIdentity
from app.agents.results import ToolInvocationRequest, ToolInvocationResult
from app.agents.tools import (
    BaseTool,
    ToolCapability,
    ToolInvoker,
    ToolRegistry,
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
from app.governance.persistence.memory import InMemoryGovernanceRepository
from app.governance.persistence.records import GovernanceDecisionRecord
from app.governance.policies.base import BaseGovernancePolicy
from app.governance.policies.chain import PolicyChain
from app.governance.subjects.base import SubjectKind


class _DecisionPolicy(BaseGovernancePolicy):
    name: ClassVar[str] = "mandatory_action_tool_gate"
    supported_stages: ClassVar[FrozenSet[EnforcementStage]] = frozenset(
        {EnforcementStage.PRE_EXECUTION}
    )
    applicable_subject_kinds: ClassVar[FrozenSet[SubjectKind]] = frozenset(
        {SubjectKind.AGENT_ACTION}
    )

    def __init__(self, decision: Decision) -> None:
        self._decision = decision

    async def evaluate(
        self, context: GovernanceContext
    ) -> Sequence[PolicyEvaluationResult]:
        return (
            PolicyEvaluationResult(
                policy_name=self.name,
                rule_id=f"tool_{self._decision.value}",
                decision=self._decision,
                reason=f"fixture returned {self._decision.value}",
            ),
        )


class _ActionTool(BaseTool):
    name: ClassVar[str] = "mutating_echo"
    capability: ClassVar[ToolCapability] = ToolCapability.ACTION
    required_capabilities: ClassVar[frozenset[str]] = frozenset(
        {"tool.mutate"}
    )

    def __init__(self, calls: list[dict[str, object]]) -> None:
        self._calls = calls

    async def invoke(
        self, request: ToolInvocationRequest, context: AgentExecutionContext
    ) -> ToolInvocationResult:
        self._calls.append(dict(request.payload))
        return ToolInvocationResult(output=dict(request.payload))


class _ReadOnlyTool(BaseTool):
    name: ClassVar[str] = "echo"
    capability: ClassVar[ToolCapability] = ToolCapability.READ_ONLY
    required_capabilities: ClassVar[frozenset[str]] = frozenset({"tool.read"})

    async def invoke(
        self, request: ToolInvocationRequest, context: AgentExecutionContext
    ) -> ToolInvocationResult:
        return ToolInvocationResult(output=dict(request.payload))


class _UndeclaredCapabilityTool(BaseTool):
    name: ClassVar[str] = "undeclared_mutating_echo"
    required_capabilities: ClassVar[frozenset[str]] = frozenset(
        {"tool.mutate"}
    )

    async def invoke(
        self, request: ToolInvocationRequest, context: AgentExecutionContext
    ) -> ToolInvocationResult:
        return ToolInvocationResult(output=dict(request.payload))


def _handlers() -> EnforcementHandlerRegistry:
    registry = EnforcementHandlerRegistry()
    for handler in (
        AllowHandler(),
        DenyHandler(),
        RedactHandler(),
        DegradeHandler(),
        EscalateHandler(),
        RequireApprovalHandler(),
    ):
        registry.register(handler)
    return registry


def _governance(
    decision: Decision,
) -> tuple[GovernanceRuntime, InMemoryGovernanceRepository]:
    persistence = InMemoryGovernanceRepository()
    chain = PolicyChain(
        chain_id="mandatory.action.tool.chain",
        stage=EnforcementStage.PRE_EXECUTION,
        policies=(_DecisionPolicy(decision),),
    )
    return (
        GovernanceRuntime(
            engine=PolicyEvaluationEngine(),
            handler_registry=_handlers(),
            chains={EnforcementStage.PRE_EXECUTION: chain},
            persistence=persistence,
        ),
        persistence,
    )


def _registry(tool: BaseTool) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(tool)
    return registry


def _context(*, tool_name: str) -> AgentExecutionContext:
    return AgentExecutionContext(
        identity=AgentIdentity(
            agent_id="test-agent",
            runtime_instance_id=uuid.uuid5(
                uuid.NAMESPACE_URL, "test-action-tool-runtime"
            ),
        ),
        execution=ExecutionIdentity(
            execution_id=uuid.uuid5(
                uuid.NAMESPACE_URL, f"test-action-tool:{tool_name}"
            ),
            request_id="req-action-tool",
        ),
        capabilities=CapabilitySet(
            (
                AgentCapability(
                    name="tool.mutate", scope=CapabilityScope.INVOKE
                ),
                AgentCapability(
                    name="tool.read", scope=CapabilityScope.READ
                ),
            )
        ),
        constraints=ExecutionConstraints(),
        causality=CausalityMetadata(),
        tenant_id="tenant-action",
    )


async def _invoke(
    *,
    invoker: ToolInvoker,
    tool_name: str,
) -> object:
    return await invoker.invoke(
        ToolInvocationRequest(
            tool_name=tool_name,
            payload={"value": 1},
            metadata={"target_resource": "external:test"},
        ),
        _context(tool_name=tool_name),
        invocation_ordinal=1,
    )


async def _invoke_pre_approved(
    *,
    invoker: ToolInvoker,
    decision_id: str,
) -> object:
    return await invoker.invoke(
        ToolInvocationRequest(
            tool_name="mutating_echo",
            payload={"value": 1},
            metadata={"target_resource": "external:test"},
        ),
        _context(tool_name="mutating_echo"),
        invocation_ordinal=1,
        pre_approved_decision_id=decision_id,
    )


def _persisted_decision(
    *,
    decision_id: str,
    decision: Decision = Decision.ALLOW,
) -> GovernanceDecisionRecord:
    return GovernanceDecisionRecord(
        decision_id=decision_id,
        decision=decision.value,
        stage=EnforcementStage.PRE_EXECUTION.value,
        policy_chain_id="manager.action_approval.v1",
        reason="manager_approved",
        decided_at=datetime.now(timezone.utc).isoformat(),
        tenant_id="tenant-action",
        subject_kind="manager_approval",
    )


def test_action_tool_without_governance_runtime_raises() -> None:
    with pytest.raises(ToolConfigurationError):
        ToolInvoker(tool_registry=_registry(_ActionTool([])))


@pytest.mark.parametrize(
    "decision",
    [Decision.DENY, Decision.DEGRADE, Decision.REDACT],
)
@pytest.mark.asyncio
async def test_non_allow_decision_never_reaches_action_tool_body(
    decision: Decision,
) -> None:
    calls: list[dict[str, object]] = []
    governance, _ = _governance(decision)
    invoker = ToolInvoker(
        tool_registry=_registry(_ActionTool(calls)),
        governance_runtime=governance,
    )

    envelope = await _invoke(invoker=invoker, tool_name="mutating_echo")

    assert envelope.is_denied
    assert envelope.trace.metadata["reason"] == "governance_not_allow"
    assert envelope.trace.governance_decision_id is not None
    assert calls == []


@pytest.mark.asyncio
async def test_action_tool_allow_with_persisted_decision_runs() -> None:
    calls: list[dict[str, object]] = []
    governance, persistence = _governance(Decision.ALLOW)
    invoker = ToolInvoker(
        tool_registry=_registry(_ActionTool(calls)),
        governance_runtime=governance,
    )

    envelope = await _invoke(invoker=invoker, tool_name="mutating_echo")

    assert envelope.is_ok
    assert calls == [{"value": 1}]
    decision_id = envelope.trace.governance_decision_id
    assert decision_id is not None
    persisted = await persistence.get_decision(
        str(decision_id), expected_tenant_id="tenant-action"
    )
    assert persisted is not None
    assert persisted.decision == Decision.ALLOW.value


@pytest.mark.asyncio
async def test_pre_approved_decision_id_allows_action_tool() -> None:
    calls: list[dict[str, object]] = []
    governance, persistence = _governance(Decision.DENY)
    decision_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "manager-approved-tool"))
    await persistence.record_decision(_persisted_decision(decision_id=decision_id))
    invoker = ToolInvoker(
        tool_registry=_registry(_ActionTool(calls)),
        governance_runtime=governance,
    )

    envelope = await _invoke_pre_approved(
        invoker=invoker,
        decision_id=decision_id,
    )

    assert envelope.is_ok
    assert calls == [{"value": 1}]
    assert str(envelope.trace.governance_decision_id) == decision_id


@pytest.mark.asyncio
async def test_pre_approved_nonexistent_decision_denies() -> None:
    calls: list[dict[str, object]] = []
    governance, _ = _governance(Decision.ALLOW)
    invoker = ToolInvoker(
        tool_registry=_registry(_ActionTool(calls)),
        governance_runtime=governance,
    )

    envelope = await _invoke_pre_approved(
        invoker=invoker,
        decision_id=str(uuid.uuid5(uuid.NAMESPACE_URL, "missing-manager-approval")),
    )

    assert envelope.is_denied
    assert envelope.trace.metadata["reason"] == "pre_approved_decision_not_found"
    assert calls == []


@pytest.mark.asyncio
async def test_read_only_tool_without_governance_runtime_runs() -> None:
    invoker = ToolInvoker(tool_registry=_registry(_ReadOnlyTool()))

    envelope = await _invoke(invoker=invoker, tool_name="echo")

    assert envelope.is_ok
    assert envelope.trace.governance_decision_id is None
    assert envelope.result is not None
    assert envelope.result.output == {"value": 1}


def test_undeclared_capability_tool_defaults_to_action() -> None:
    with pytest.raises(ToolConfigurationError):
        ToolInvoker(tool_registry=_registry(_UndeclaredCapabilityTool()))
