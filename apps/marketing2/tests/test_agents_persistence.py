"""Sprint J — agent runtime persistence tests.

Properties pinned:

* records round-trip cleanly through `to_dict` → `from_dict`,
* `execution_envelope_to_records` decomposes one envelope into one
  execution record + N tool records preserving order and lineage,
* `InMemoryAgentRepository` is write-once for executions,
* point reads + queries return what was written,
* `get_children` returns direct children sorted by `started_at`.
"""

from __future__ import annotations

import uuid
from typing import Any, ClassVar, Mapping

import pytest

from app.agents.capabilities import AgentCapability
from app.agents.context import AgentExecutionContext
from app.agents.enums import CapabilityScope
from app.agents.persistence import (
    AgentExecutionRecord,
    BaseAgentRepository,
    ExecutionQuery,
    InMemoryAgentRepository,
    StateTransitionRecord,
    ToolInvocationRecord,
    execution_envelope_to_records,
)
from app.agents.results import (
    AgentExecutionResult,
    ToolInvocationRequest,
    ToolInvocationResult,
)
from app.agents.runtime import AgentRegistry, AgentRuntime, BaseAgent
from app.agents.tools import AgentToolSession, BaseTool, ToolInvoker, ToolRegistry


# ─── Round-trip tests ────────────────────────────────────────────────


def test_state_transition_record_round_trip() -> None:
    record = StateTransitionRecord(
        from_state="created",
        to_state="ready",
        transitioned_at="2026-05-15T03:30:00+00:00",
        reason="context_built",
    )
    assert StateTransitionRecord.from_dict(record.to_dict()) == record


def test_tool_invocation_record_round_trip() -> None:
    record = ToolInvocationRecord(
        invocation_id=str(uuid.uuid4()),
        execution_id=str(uuid.uuid4()),
        tool_name="echo",
        status="ok",
        started_at="2026-05-15T03:30:00+00:00",
        ended_at="2026-05-15T03:30:00+00:00",
        latency_ms=1.2,
        governance_decision_id=str(uuid.uuid4()),
        metadata={"reason": "ok"},
    )
    assert ToolInvocationRecord.from_dict(record.to_dict()) == record


def test_agent_execution_record_round_trip() -> None:
    record = AgentExecutionRecord(
        execution_id=str(uuid.uuid4()),
        runtime_instance_id=str(uuid.uuid4()),
        agent_id="ok",
        correlation_id=str(uuid.uuid4()),
        parent_execution_id=str(uuid.uuid4()),
        parent_chain=(str(uuid.uuid4()), str(uuid.uuid4())),
        request_id="req-1",
        tenant_id="t-1",
        final_state="completed",
        started_at="2026-05-15T03:30:00+00:00",
        ended_at="2026-05-15T03:30:01+00:00",
        latency_ms=10.5,
        state_transitions=(
            StateTransitionRecord(
                from_state="created",
                to_state="ready",
                transitioned_at="2026-05-15T03:30:00+00:00",
                reason="context_built",
            ),
        ),
        tool_invocation_count=2,
        tool_invocation_ids=(str(uuid.uuid4()), str(uuid.uuid4())),
        governance_decision_ids=(str(uuid.uuid4()),),
        metadata={"initiator": "system"},
    )
    assert AgentExecutionRecord.from_dict(record.to_dict()) == record


# ─── Envelope decomposition tests ────────────────────────────────────


class _EchoTool(BaseTool):
    name: ClassVar[str] = "echo"
    required_capabilities: ClassVar[frozenset[str]] = frozenset({"tool.echo"})

    async def invoke(
        self, request: ToolInvocationRequest, context: AgentExecutionContext
    ) -> ToolInvocationResult:
        return ToolInvocationResult(output=dict(request.payload))


class _MultiCallAgent(BaseAgent):
    agent_id: ClassVar[str] = "multi"
    declared_capabilities: ClassVar[tuple[AgentCapability, ...]] = (
        AgentCapability(name="tool.echo", scope=CapabilityScope.INVOKE),
    )

    async def run(
        self,
        request: Mapping[str, Any],
        context: AgentExecutionContext,
        session: AgentToolSession,
    ) -> AgentExecutionResult:
        for i in range(3):
            await session.invoke(
                ToolInvocationRequest(tool_name="echo", payload={"i": i})
            )
        return AgentExecutionResult(output={"count": 3})


def _runtime() -> AgentRuntime:
    tools = ToolRegistry()
    tools.register(_EchoTool())
    invoker = ToolInvoker(tool_registry=tools)
    agents = AgentRegistry()
    agents.register(_MultiCallAgent())
    return AgentRuntime(agent_registry=agents, tool_invoker=invoker)


@pytest.mark.asyncio
async def test_envelope_decomposes_into_records_preserving_order() -> None:
    rt = _runtime()
    env = await rt.execute("multi", {}, tenant_id="t-7")
    exec_record, tool_records = execution_envelope_to_records(
        env, tenant_id="t-7"
    )
    assert exec_record.execution_id == str(env.trace.execution_id)
    assert exec_record.tenant_id == "t-7"
    assert exec_record.tool_invocation_count == 3
    assert len(tool_records) == 3
    # Order preserved.
    for env_tool, record in zip(env.tool_envelopes, tool_records):
        assert record.invocation_id == str(env_tool.trace.invocation_id)
        assert record.tool_name == env_tool.trace.tool_name


# ─── Repository tests ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_repository_executions_are_write_once() -> None:
    repo: BaseAgentRepository = InMemoryAgentRepository()
    record = _make_execution_record(execution_id="e-1")
    await repo.record_execution(record)
    with pytest.raises(ValueError):
        await repo.record_execution(record)


@pytest.mark.asyncio
async def test_repository_tool_invocations_are_write_once() -> None:
    repo: BaseAgentRepository = InMemoryAgentRepository()
    inv = ToolInvocationRecord(
        invocation_id="i-1",
        execution_id="e-1",
        tool_name="echo",
        status="ok",
        started_at="2026-05-15T03:30:00+00:00",
        ended_at="2026-05-15T03:30:00+00:00",
        latency_ms=1.0,
    )
    await repo.record_tool_invocation(inv)
    with pytest.raises(ValueError):
        await repo.record_tool_invocation(inv)


@pytest.mark.asyncio
async def test_repository_query_executions_filters_correctly() -> None:
    repo: BaseAgentRepository = InMemoryAgentRepository()
    for idx, agent_id in enumerate(["a", "b", "a", "b"]):
        await repo.record_execution(
            _make_execution_record(
                execution_id=f"e-{idx}",
                agent_id=agent_id,
                started_at=f"2026-05-15T03:30:0{idx}+00:00",
            )
        )
    page = await repo.query_executions(ExecutionQuery(agent_id="a"))
    assert page.total == 2
    assert all(r.agent_id == "a" for r in page.items)
    # Sorted by started_at.
    assert [r.execution_id for r in page.items] == ["e-0", "e-2"]


@pytest.mark.asyncio
async def test_repository_get_children_returns_direct_descendants() -> None:
    repo: BaseAgentRepository = InMemoryAgentRepository()
    parent_id = "p-1"
    await repo.record_execution(
        _make_execution_record(execution_id=parent_id, agent_id="parent")
    )
    for idx in range(3):
        await repo.record_execution(
            _make_execution_record(
                execution_id=f"c-{idx}",
                parent_execution_id=parent_id,
                started_at=f"2026-05-15T03:31:0{2 - idx}+00:00",
            )
        )
    children = await repo.get_children(parent_id)
    assert len(children) == 3
    # Sorted by started_at — c-2 has the earliest timestamp.
    assert [c.execution_id for c in children] == ["c-2", "c-1", "c-0"]


# ─── Helpers ─────────────────────────────────────────────────────────


def _make_execution_record(
    *,
    execution_id: str,
    agent_id: str = "ok",
    parent_execution_id: str | None = None,
    started_at: str = "2026-05-15T03:30:00+00:00",
) -> AgentExecutionRecord:
    return AgentExecutionRecord(
        execution_id=execution_id,
        runtime_instance_id="rt-1",
        agent_id=agent_id,
        correlation_id=None,
        parent_execution_id=parent_execution_id,
        parent_chain=(),
        request_id=None,
        tenant_id=None,
        final_state="completed",
        started_at=started_at,
        ended_at=started_at,
        latency_ms=1.0,
        state_transitions=(),
        tool_invocation_count=0,
    )
