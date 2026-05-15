"""Sprint K — `SupervisorRuntime` end-to-end.

Properties pinned:

* never raises — every outcome lands on an `ExecutionInspectionEnvelope`,
* request validation: requires exactly one of live / replay,
* live execution_id mismatch is rejected,
* whitelist filtering honours sorted-name order,
* clean execution produces ACCEPT envelope,
* failed execution produces ESCALATE / REJECT envelope,
* evaluator error is contained and surfaced as `ERRORED` status
  without breaking the inspection,
* runtime instance id is stable for one runtime instance.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, ClassVar, Mapping

import pytest

from app.agents.capabilities import AgentCapability, CapabilitySet
from app.agents.context import AgentExecutionContext
from app.agents.enums import CapabilityScope, ExecutionState
from app.agents.envelopes import (
    AgentExecutionEnvelope,
    ToolInvocationEnvelope,
)
from app.agents.results import (
    AgentExecutionResult,
    ToolInvocationRequest,
    ToolInvocationResult,
)
from app.agents.runtime import AgentRegistry, AgentRuntime, BaseAgent
from app.agents.tools import AgentToolSession, BaseTool, ToolInvoker, ToolRegistry
from app.supervisor.contracts.requests import ExecutionInspectionRequest
from app.supervisor.enums import (
    EvaluationStatus,
    InspectionMode,
    SupervisorDecisionKind,
)
from app.supervisor.evaluators.base import BaseEvaluator
from app.supervisor.evaluators.builtin import (
    ExecutionCompletionEvaluator,
    GovernanceComplianceEvaluator,
    StateMachineHealthEvaluator,
    ToolInvocationEvaluator,
)
from app.supervisor.evaluators.registry import EvaluatorRegistry
from app.supervisor.runtime.runtime import SupervisorRuntime


# ─── Helpers / fixtures ──────────────────────────────────────────────


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


def _build_runtime() -> AgentRuntime:
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
async def test_inspect_accepts_clean_execution() -> None:
    runtime = _build_runtime()
    supervisor = _build_supervisor()
    envelope = await runtime.execute("ok", {})

    inspection = await supervisor.inspect(
        ExecutionInspectionRequest(
            execution_id=envelope.trace.execution_id,
            live_envelope=envelope,
        )
    )
    assert inspection.is_ok
    result = inspection.unwrap()
    assert result.inspection_mode is InspectionMode.LIVE
    assert result.decision.kind is SupervisorDecisionKind.ACCEPT
    assert result.decision.findings == ()
    assert result.decision.escalations == ()
    # Evaluators ran in sorted name order.
    names = [e.evaluator_name for e in result.evaluations]
    assert names == sorted(names)


@pytest.mark.asyncio
async def test_inspect_escalates_failed_execution() -> None:
    runtime = _build_runtime()
    supervisor = _build_supervisor()
    envelope = await runtime.execute("boom", {})

    inspection = await supervisor.inspect(
        ExecutionInspectionRequest(
            execution_id=envelope.trace.execution_id,
            live_envelope=envelope,
        )
    )
    assert inspection.is_ok
    result = inspection.unwrap()
    # Failed execution → HIGH severity finding → ESCALATE
    assert result.decision.kind is SupervisorDecisionKind.ESCALATE
    assert len(result.decision.escalations) == 1
    assert result.decision.escalations[0].level.value == "review"
    assert any(
        f.code == "execution.failed" for f in result.decision.findings
    )


@pytest.mark.asyncio
async def test_inspect_rejects_missing_source() -> None:
    supervisor = _build_supervisor()
    inspection = await supervisor.inspect(
        ExecutionInspectionRequest(execution_id=uuid.uuid4())
    )
    assert not inspection.is_ok
    assert inspection.error is not None


@pytest.mark.asyncio
async def test_inspect_rejects_both_sources() -> None:
    runtime = _build_runtime()
    supervisor = _build_supervisor()
    envelope = await runtime.execute("ok", {})

    from app.agents.persistence.serializers import (
        execution_envelope_to_records,
    )

    execution_rec, _ = execution_envelope_to_records(envelope)

    inspection = await supervisor.inspect(
        ExecutionInspectionRequest(
            execution_id=envelope.trace.execution_id,
            live_envelope=envelope,
            recorded_execution=execution_rec,
        )
    )
    assert not inspection.is_ok


@pytest.mark.asyncio
async def test_inspect_rejects_execution_id_mismatch() -> None:
    runtime = _build_runtime()
    supervisor = _build_supervisor()
    envelope = await runtime.execute("ok", {})
    inspection = await supervisor.inspect(
        ExecutionInspectionRequest(
            execution_id=uuid.uuid4(),  # mismatched
            live_envelope=envelope,
        )
    )
    assert not inspection.is_ok


@pytest.mark.asyncio
async def test_inspect_whitelist_runs_subset_in_sorted_order() -> None:
    runtime = _build_runtime()
    supervisor = _build_supervisor()
    envelope = await runtime.execute("ok", {})

    inspection = await supervisor.inspect(
        ExecutionInspectionRequest(
            execution_id=envelope.trace.execution_id,
            live_envelope=envelope,
            evaluator_names=(
                "state_machine_health",
                "execution_completion",
            ),
        )
    )
    result = inspection.unwrap()
    names = [e.evaluator_name for e in result.evaluations]
    assert names == ["execution_completion", "state_machine_health"]


@pytest.mark.asyncio
async def test_inspect_unknown_evaluator_in_whitelist_fails_cleanly() -> None:
    runtime = _build_runtime()
    supervisor = _build_supervisor()
    envelope = await runtime.execute("ok", {})

    inspection = await supervisor.inspect(
        ExecutionInspectionRequest(
            execution_id=envelope.trace.execution_id,
            live_envelope=envelope,
            evaluator_names=("does_not_exist",),
        )
    )
    assert not inspection.is_ok


# ─── Evaluator error containment ─────────────────────────────────────


class _ExplodingEvaluator(BaseEvaluator):
    name: ClassVar[str] = "exploding"

    async def evaluate(self, view):  # type: ignore[override]
        raise RuntimeError("evaluator blew up")


@pytest.mark.asyncio
async def test_inspect_contains_evaluator_failure() -> None:
    runtime = _build_runtime()
    registry = EvaluatorRegistry()
    registry.register(ExecutionCompletionEvaluator())
    registry.register(_ExplodingEvaluator())
    supervisor = SupervisorRuntime(evaluator_registry=registry)

    envelope = await runtime.execute("ok", {})
    inspection = await supervisor.inspect(
        ExecutionInspectionRequest(
            execution_id=envelope.trace.execution_id,
            live_envelope=envelope,
        )
    )
    # Inspection still produces a result; the exploding evaluator is
    # surfaced as ERRORED.
    assert inspection.is_ok
    result = inspection.unwrap()
    statuses = {e.evaluator_name: e.status for e in result.evaluations}
    assert statuses["exploding"] is EvaluationStatus.ERRORED
    assert statuses["execution_completion"] is EvaluationStatus.PASSED


# ─── Runtime-instance identity ───────────────────────────────────────


@pytest.mark.asyncio
async def test_runtime_instance_id_stable_across_calls() -> None:
    runtime = _build_runtime()
    supervisor = _build_supervisor()
    envelope1 = await runtime.execute("ok", {})
    envelope2 = await runtime.execute("ok", {})

    r1 = (
        await supervisor.inspect(
            ExecutionInspectionRequest(
                execution_id=envelope1.trace.execution_id,
                live_envelope=envelope1,
            )
        )
    ).unwrap()
    r2 = (
        await supervisor.inspect(
            ExecutionInspectionRequest(
                execution_id=envelope2.trace.execution_id,
                live_envelope=envelope2,
            )
        )
    ).unwrap()
    assert r1.runtime_instance_id == r2.runtime_instance_id
    assert r1.inspection_id != r2.inspection_id
