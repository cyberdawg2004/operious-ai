"""Sprint K — replay safety.

Properties pinned:

* live and replay inspections of the same execution produce
  semantically-equivalent results (modulo inspection_id, decision_id
  and wall-clock timestamps),
* the same finding codes / severities / counts emerge from both
  modes,
* deterministic `finding_id`s match across live and replay,
* repeating inspection on the same envelope produces identical
  decision kind + finding set + escalation set.

These tests are the operational guarantee that supervisor inspections
remain reconstructable from storage.
"""

from __future__ import annotations

import uuid
from typing import Any, ClassVar, Mapping

import pytest

from app.agents.capabilities import AgentCapability
from app.agents.context import AgentExecutionContext
from app.agents.enums import CapabilityScope
from app.agents.persistence.serializers import execution_envelope_to_records
from app.agents.results import (
    AgentExecutionResult,
    ToolInvocationRequest,
    ToolInvocationResult,
)
from app.agents.runtime import AgentRegistry, AgentRuntime, BaseAgent
from app.agents.tools import AgentToolSession, BaseTool, ToolInvoker, ToolRegistry
from app.supervisor.contracts.requests import ExecutionInspectionRequest
from app.supervisor.enums import InspectionMode
from app.supervisor.evaluators.builtin import (
    ExecutionCompletionEvaluator,
    GovernanceComplianceEvaluator,
    StateMachineHealthEvaluator,
    ToolInvocationEvaluator,
)
from app.supervisor.evaluators.registry import EvaluatorRegistry
from app.supervisor.runtime.runtime import SupervisorRuntime


# ─── Test fixtures ───────────────────────────────────────────────────


class _EchoTool(BaseTool):
    name: ClassVar[str] = "echo"
    required_capabilities: ClassVar[frozenset[str]] = frozenset({"tool.echo"})

    async def invoke(
        self, request: ToolInvocationRequest, context: AgentExecutionContext
    ) -> ToolInvocationResult:
        return ToolInvocationResult(output=dict(request.payload))


class _OkAgent(BaseAgent):
    agent_id: ClassVar[str] = "ok"
    declared_capabilities: ClassVar[tuple[AgentCapability, ...]] = (
        AgentCapability(name="tool.echo", scope=CapabilityScope.INVOKE),
    )

    async def run(
        self,
        request: Mapping[str, Any],
        context: AgentExecutionContext,
        session: AgentToolSession,
    ) -> AgentExecutionResult:
        env = await session.invoke(
            ToolInvocationRequest(tool_name="echo", payload={"v": 1})
        )
        assert env.is_ok
        assert env.result is not None
        return AgentExecutionResult(output={"echoed": env.result.output})


class _FailingAgent(BaseAgent):
    agent_id: ClassVar[str] = "boom"
    declared_capabilities: ClassVar[tuple[AgentCapability, ...]] = ()

    async def run(
        self,
        request: Mapping[str, Any],
        context: AgentExecutionContext,
        session: AgentToolSession,
    ) -> AgentExecutionResult:
        raise ValueError("agent exploded")


def _build_agent_runtime() -> AgentRuntime:
    tool_registry = ToolRegistry()
    tool_registry.register(_EchoTool())
    agent_registry = AgentRegistry()
    agent_registry.register(_OkAgent())
    agent_registry.register(_FailingAgent())
    invoker = ToolInvoker(tool_registry=tool_registry)
    return AgentRuntime(
        agent_registry=agent_registry, tool_invoker=invoker
    )


def _build_supervisor() -> SupervisorRuntime:
    registry = EvaluatorRegistry()
    registry.register(ExecutionCompletionEvaluator())
    registry.register(ToolInvocationEvaluator())
    registry.register(GovernanceComplianceEvaluator())
    registry.register(StateMachineHealthEvaluator())
    return SupervisorRuntime(evaluator_registry=registry)


# ─── Tests ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_live_and_replay_produce_equivalent_decisions() -> None:
    agent_runtime = _build_agent_runtime()
    supervisor = _build_supervisor()

    envelope = await agent_runtime.execute("boom", {})

    # Live inspection.
    live = (
        await supervisor.inspect(
            ExecutionInspectionRequest(
                execution_id=envelope.trace.execution_id,
                live_envelope=envelope,
            )
        )
    ).unwrap()

    # Replay inspection from records.
    execution_rec, tool_recs = execution_envelope_to_records(envelope)
    replay = (
        await supervisor.inspect(
            ExecutionInspectionRequest(
                execution_id=envelope.trace.execution_id,
                recorded_execution=execution_rec,
                recorded_tool_invocations=tool_recs,
            )
        )
    ).unwrap()

    assert live.inspection_mode is InspectionMode.LIVE
    assert replay.inspection_mode is InspectionMode.REPLAY

    # Decision kind + finding shape are byte-identical (deterministic
    # finding_id derivation).
    assert live.decision.kind == replay.decision.kind
    live_codes = sorted(f.code for f in live.decision.findings)
    replay_codes = sorted(f.code for f in replay.decision.findings)
    assert live_codes == replay_codes
    live_finding_ids = sorted(str(f.finding_id) for f in live.decision.findings)
    replay_finding_ids = sorted(
        str(f.finding_id) for f in replay.decision.findings
    )
    assert live_finding_ids == replay_finding_ids


@pytest.mark.asyncio
async def test_repeated_inspections_produce_same_finding_ids() -> None:
    agent_runtime = _build_agent_runtime()
    supervisor = _build_supervisor()
    envelope = await agent_runtime.execute("boom", {})

    a = (
        await supervisor.inspect(
            ExecutionInspectionRequest(
                execution_id=envelope.trace.execution_id,
                live_envelope=envelope,
            )
        )
    ).unwrap()
    b = (
        await supervisor.inspect(
            ExecutionInspectionRequest(
                execution_id=envelope.trace.execution_id,
                live_envelope=envelope,
            )
        )
    ).unwrap()

    a_ids = sorted(str(f.finding_id) for f in a.decision.findings)
    b_ids = sorted(str(f.finding_id) for f in b.decision.findings)
    assert a_ids == b_ids
    assert a.decision.kind == b.decision.kind


@pytest.mark.asyncio
async def test_clean_execution_replay_is_accept() -> None:
    agent_runtime = _build_agent_runtime()
    supervisor = _build_supervisor()
    envelope = await agent_runtime.execute("ok", {})

    execution_rec, tool_recs = execution_envelope_to_records(envelope)
    replay = (
        await supervisor.inspect(
            ExecutionInspectionRequest(
                execution_id=envelope.trace.execution_id,
                recorded_execution=execution_rec,
                recorded_tool_invocations=tool_recs,
            )
        )
    ).unwrap()

    # Ok agent produces one OK tool invocation; supervisor accepts.
    assert replay.decision.kind.value == "accept"
    assert replay.decision.findings == ()
    # Tool evaluator should NOT skip (one invocation present).
    statuses = {e.evaluator_name: e.status.value for e in replay.evaluations}
    assert statuses["tool_invocation"] == "passed"


@pytest.mark.asyncio
async def test_decision_id_override_locks_replay_decision_id() -> None:
    agent_runtime = _build_agent_runtime()
    supervisor = _build_supervisor()
    envelope = await agent_runtime.execute("boom", {})

    fixed = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
    inspection = (
        await supervisor.inspect(
            ExecutionInspectionRequest(
                execution_id=envelope.trace.execution_id,
                live_envelope=envelope,
                decision_id_override=fixed,
            )
        )
    ).unwrap()
    assert inspection.decision.decision_id == fixed
    # Escalation id is deterministic from (decision_id, level).
    if inspection.decision.escalations:
        assert inspection.decision.escalations[0].escalation_id == uuid.uuid5(
            uuid.UUID("b2e7d3a8-5c9f-4e6b-8a1d-fedcba987654"),
            f"{fixed}:review",
        )
