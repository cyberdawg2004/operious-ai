"""Sprint J — agent runtime + governance integration tests.

Properties pinned:

* tool invocations route through the configured `GovernanceRuntime`
  with an `AgentActionGovernanceSubject`,
* DENY governance decisions block the tool call (envelope is denied,
  not failed),
* ALLOW governance decisions allow the tool call to proceed,
* the governance decision id is captured on the tool trace AND on
  the execution trace's `governance_decision_ids` lineage,
* every governance envelope is captured on the execution envelope's
  `governance_envelopes` collection,
* governance integration is **opt-in** — the runtime works without
  a governance runtime configured (smoke).
"""

from __future__ import annotations

from typing import Any, ClassVar, FrozenSet, Mapping, Sequence

import pytest

from app.agents.capabilities import AgentCapability, ExecutionConstraints
from app.agents.context import AgentExecutionContext
from app.agents.enums import CapabilityScope
from app.agents.results import (
    AgentExecutionResult,
    ToolInvocationRequest,
    ToolInvocationResult,
)
from app.agents.runtime import AgentRegistry, AgentRuntime, BaseAgent
from app.agents.tools import AgentToolSession, BaseTool, ToolInvoker, ToolRegistry
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
from app.governance.enums import Decision, EnforcementStage, ViolationSeverity
from app.governance.evaluators.engine import PolicyEvaluationEngine
from app.governance.policies.base import BaseGovernancePolicy
from app.governance.policies.chain import PolicyChain
from app.governance.subjects.agent_actions import AgentActionGovernanceSubject
from app.governance.subjects.base import SubjectKind


# ─── Test policies ──────────────────────────────────────────────────


class _AgentActionPolicy(BaseGovernancePolicy):
    """Decides DENY iff the requested tool name is in `denied_tools`."""

    name: ClassVar[str] = "agent_action_gate"
    supported_stages: ClassVar[FrozenSet[EnforcementStage]] = frozenset(
        {EnforcementStage.PRE_EXECUTION}
    )
    applicable_subject_kinds: ClassVar[FrozenSet[SubjectKind]] = frozenset(
        {SubjectKind.AGENT_ACTION}
    )

    def __init__(self, denied_tools: frozenset[str] = frozenset()) -> None:
        self._denied = denied_tools

    async def evaluate(
        self, context: GovernanceContext
    ) -> Sequence[PolicyEvaluationResult]:
        subject = context.subject
        assert isinstance(subject, AgentActionGovernanceSubject)
        if subject.tool_name in self._denied:
            return (
                PolicyEvaluationResult(
                    policy_name=self.name,
                    rule_id="tool_denylisted",
                    decision=Decision.DENY,
                    severity=ViolationSeverity.HIGH,
                    reason=f"tool {subject.tool_name!r} is denylisted",
                ),
            )
        return (
            PolicyEvaluationResult(
                policy_name=self.name,
                rule_id="tool_allowed",
                decision=Decision.ALLOW,
                severity=ViolationSeverity.LOW,
                reason="tool not in denylist",
            ),
        )


def _full_handler_registry() -> EnforcementHandlerRegistry:
    reg = EnforcementHandlerRegistry()
    for handler in (
        AllowHandler(),
        DenyHandler(),
        RedactHandler(),
        DegradeHandler(),
        EscalateHandler(),
        RequireApprovalHandler(),
    ):
        reg.register(handler)
    return reg


def _governance(
    *, denied_tools: frozenset[str] = frozenset()
) -> GovernanceRuntime:
    chain = PolicyChain(
        chain_id="agent.action.chain",
        stage=EnforcementStage.PRE_EXECUTION,
        policies=(_AgentActionPolicy(denied_tools=denied_tools),),
    )
    return GovernanceRuntime(
        engine=PolicyEvaluationEngine(),
        handler_registry=_full_handler_registry(),
        chains={EnforcementStage.PRE_EXECUTION: chain},
    )


# ─── Test agents/tools ──────────────────────────────────────────────


class _EchoTool(BaseTool):
    name: ClassVar[str] = "echo"
    required_capabilities: ClassVar[frozenset[str]] = frozenset({"tool.echo"})

    async def invoke(
        self, request: ToolInvocationRequest, context: AgentExecutionContext
    ) -> ToolInvocationResult:
        return ToolInvocationResult(output=dict(request.payload))


class _SearchTool(BaseTool):
    name: ClassVar[str] = "search"
    required_capabilities: ClassVar[frozenset[str]] = frozenset({"tool.search"})

    async def invoke(
        self, request: ToolInvocationRequest, context: AgentExecutionContext
    ) -> ToolInvocationResult:
        return ToolInvocationResult(output={"results": []})


class _MultiToolAgent(BaseAgent):
    agent_id: ClassVar[str] = "multi"
    declared_capabilities: ClassVar[tuple[AgentCapability, ...]] = (
        AgentCapability(name="tool.echo", scope=CapabilityScope.INVOKE),
        AgentCapability(name="tool.search", scope=CapabilityScope.INVOKE),
    )

    async def run(
        self,
        request: Mapping[str, Any],
        context: AgentExecutionContext,
        session: AgentToolSession,
    ) -> AgentExecutionResult:
        await session.invoke(ToolInvocationRequest(tool_name="echo"))
        await session.invoke(ToolInvocationRequest(tool_name="search"))
        return AgentExecutionResult(
            output={"count": session.invocation_count}
        )


def _runtime_with(
    governance: GovernanceRuntime | None,
) -> AgentRuntime:
    tools = ToolRegistry()
    tools.register(_EchoTool())
    tools.register(_SearchTool())
    invoker = ToolInvoker(
        tool_registry=tools, governance_runtime=governance
    )
    agents = AgentRegistry()
    agents.register(_MultiToolAgent())
    return AgentRuntime(agent_registry=agents, tool_invoker=invoker)


# ─── Tests ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_governance_allow_lets_tool_proceed() -> None:
    rt = _runtime_with(_governance())
    env = await rt.execute("multi", {})
    assert env.is_ok
    for tool_env in env.tool_envelopes:
        assert tool_env.is_ok
        assert tool_env.governance_envelope is not None
        assert tool_env.governance_envelope.is_ok
        decision = tool_env.governance_envelope.unwrap()
        assert decision.is_allow


@pytest.mark.asyncio
async def test_governance_deny_blocks_specific_tool() -> None:
    gov = _governance(denied_tools=frozenset({"echo"}))
    rt = _runtime_with(gov)
    env = await rt.execute("multi", {})
    assert env.is_ok  # agent itself completed
    # First call (echo) was denied; second (search) was allowed.
    echo_env, search_env = env.tool_envelopes
    assert echo_env.is_denied
    assert echo_env.trace.metadata["reason"] == "governance_denied"
    assert echo_env.trace.governance_decision_id is not None
    assert search_env.is_ok


@pytest.mark.asyncio
async def test_governance_decision_ids_lineage_on_execution_trace() -> None:
    rt = _runtime_with(_governance())
    env = await rt.execute("multi", {})
    # One decision per tool invocation.
    assert len(env.trace.governance_decision_ids) == 2
    assert len(env.governance_envelopes) == 2
    # Decision ids on the trace match those on the tool envelopes.
    tool_ids = tuple(
        e.trace.governance_decision_id for e in env.tool_envelopes
    )
    assert env.trace.governance_decision_ids == tool_ids


@pytest.mark.asyncio
async def test_governance_subject_carries_agent_action_vocabulary() -> None:
    """The governance evaluation must see an `AgentActionGovernanceSubject`
    populated with agent_id, tool_name, capability."""
    captured: list[GovernanceContext] = []

    class _CapturingPolicy(BaseGovernancePolicy):
        name: ClassVar[str] = "capture"
        supported_stages: ClassVar[FrozenSet[EnforcementStage]] = frozenset(
            {EnforcementStage.PRE_EXECUTION}
        )
        applicable_subject_kinds: ClassVar[FrozenSet[SubjectKind]] = frozenset(
            {SubjectKind.AGENT_ACTION}
        )

        async def evaluate(
            self, context: GovernanceContext
        ) -> Sequence[PolicyEvaluationResult]:
            captured.append(context)
            return (
                PolicyEvaluationResult(
                    policy_name=self.name,
                    rule_id="ok",
                    decision=Decision.ALLOW,
                ),
            )

    chain = PolicyChain(
        chain_id="capture.chain",
        stage=EnforcementStage.PRE_EXECUTION,
        policies=(_CapturingPolicy(),),
    )
    gov = GovernanceRuntime(
        engine=PolicyEvaluationEngine(),
        handler_registry=_full_handler_registry(),
        chains={EnforcementStage.PRE_EXECUTION: chain},
    )
    rt = _runtime_with(gov)
    await rt.execute("multi", {})

    assert len(captured) == 2
    for ctx in captured:
        subject = ctx.subject
        assert isinstance(subject, AgentActionGovernanceSubject)
        assert subject.agent_id == "multi"
        assert subject.tool_name in ("echo", "search")
        assert subject.kind is SubjectKind.AGENT_ACTION
        assert ctx.action == "agent.tool_invocation"
        assert ctx.actor == "agent:multi"
        assert ctx.stage is EnforcementStage.PRE_EXECUTION


@pytest.mark.asyncio
async def test_runtime_works_without_governance_configured() -> None:
    rt = _runtime_with(None)
    env = await rt.execute("multi", {})
    assert env.is_ok
    assert env.governance_envelopes == ()
    for tool_env in env.tool_envelopes:
        assert tool_env.is_ok
        assert tool_env.governance_envelope is None
        assert tool_env.trace.governance_decision_id is None


@pytest.mark.asyncio
async def test_substrate_constraints_evaluated_before_governance() -> None:
    """Ordering invariant: a tool blocked by `allowed_tools` never reaches
    the governance runtime — saves a round-trip when constraints are
    sufficient.
    """
    captured: list[GovernanceContext] = []

    class _CapturingPolicy(BaseGovernancePolicy):
        name: ClassVar[str] = "capture"
        supported_stages: ClassVar[FrozenSet[EnforcementStage]] = frozenset(
            {EnforcementStage.PRE_EXECUTION}
        )
        applicable_subject_kinds: ClassVar[FrozenSet[SubjectKind]] = frozenset(
            {SubjectKind.AGENT_ACTION}
        )

        async def evaluate(
            self, context: GovernanceContext
        ) -> Sequence[PolicyEvaluationResult]:
            captured.append(context)
            return (
                PolicyEvaluationResult(
                    policy_name=self.name,
                    rule_id="ok",
                    decision=Decision.ALLOW,
                ),
            )

    chain = PolicyChain(
        chain_id="capture.chain",
        stage=EnforcementStage.PRE_EXECUTION,
        policies=(_CapturingPolicy(),),
    )
    gov = GovernanceRuntime(
        engine=PolicyEvaluationEngine(),
        handler_registry=_full_handler_registry(),
        chains={EnforcementStage.PRE_EXECUTION: chain},
    )
    rt = _runtime_with(gov)
    constraints = ExecutionConstraints(allowed_tools=("search",))
    env = await rt.execute("multi", {}, constraints=constraints)
    # Echo blocked by constraints (no governance call); search allowed
    # with one governance call.
    assert env.tool_envelopes[0].is_denied
    assert env.tool_envelopes[0].trace.metadata["reason"] == "constraint_blocked"
    assert env.tool_envelopes[0].governance_envelope is None
    assert env.tool_envelopes[1].is_ok
    assert len(captured) == 1
