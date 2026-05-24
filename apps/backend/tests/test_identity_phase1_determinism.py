"""Wedge 3 Phase 1 identity determinism tests."""

from __future__ import annotations

import importlib
import uuid
from typing import Any, ClassVar, Mapping, Type

import pytest

from app.agents.capabilities import AgentCapability
from app.agents.context import AgentExecutionContext
from app.agents.enums import CapabilityScope
from app.agents.results import (
    AgentExecutionResult,
    ToolInvocationRequest,
    ToolInvocationResult,
)
from app.agents.runtime import AgentRegistry, AgentRuntime, BaseAgent
from app.agents.tools import AgentToolSession, BaseTool, ToolInvoker, ToolRegistry
from app.hardening import (
    HardeningRuntime,
    InMemoryHardeningPersistence,
    ValidateLineageRequest,
)
from app.hardening.audits.recorder import HardeningAuditRecorder
from app.middleware.request_context import derive_request_id_from_scope


class _EchoTool(BaseTool):
    name: ClassVar[str] = "echo"
    required_capabilities: ClassVar[frozenset[str]] = frozenset({"tool.echo"})

    async def invoke(
        self,
        request: ToolInvocationRequest,
        context: AgentExecutionContext,
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


class _DoubleCallAgent(BaseAgent):
    agent_id: ClassVar[str] = "double"
    declared_capabilities: ClassVar[tuple[AgentCapability, ...]] = (
        AgentCapability(name="tool.echo", scope=CapabilityScope.INVOKE),
    )

    async def run(
        self,
        request: Mapping[str, Any],
        context: AgentExecutionContext,
        session: AgentToolSession,
    ) -> AgentExecutionResult:
        first = await session.invoke(ToolInvocationRequest(tool_name="echo"))
        second = await session.invoke(ToolInvocationRequest(tool_name="echo"))
        return AgentExecutionResult(
            output={
                "invocations": (
                    str(first.trace.invocation_id),
                    str(second.trace.invocation_id),
                )
            }
        )


class _AlternateRecorder(HardeningAuditRecorder):
    pass


def _agent_runtime(
    *,
    runtime_cls: Type[AgentRuntime] = AgentRuntime,
    invoker_cls: Type[ToolInvoker] = ToolInvoker,
) -> AgentRuntime:
    tools = ToolRegistry()
    tools.register(_EchoTool())
    agents = AgentRegistry()
    agents.register(_OkAgent())
    agents.register(_DoubleCallAgent())
    return runtime_cls(
        agent_registry=agents,
        tool_invoker=invoker_cls(tool_registry=tools),
    )


def test_fallback_request_id_is_deterministic_and_reload_safe() -> None:
    inputs = {
        "method": "POST",
        "path": "/api/v1/tickets",
        "query_string": "source=zendesk",
        "host": "operious.local",
        "client": "203.0.113.10",
        "user_agent": "phase-1-test",
    }

    first = derive_request_id_from_scope(**inputs)
    assert derive_request_id_from_scope(**inputs) == first

    changed = derive_request_id_from_scope(
        **{**inputs, "query_string": "source=email"}
    )
    assert changed != first
    assert uuid.UUID(hex=first).hex == first

    request_context = importlib.import_module("app.middleware.request_context")
    request_context = importlib.reload(request_context)
    assert request_context.derive_request_id_from_scope(**inputs) == first


@pytest.mark.asyncio
async def test_hardening_runtime_ids_are_deterministic_and_reload_safe() -> None:
    first = HardeningRuntime(
        persistence=InMemoryHardeningPersistence()
    ).runtime_instance_id
    second = HardeningRuntime(
        persistence=InMemoryHardeningPersistence()
    ).runtime_instance_id
    different = HardeningRuntime(
        persistence=InMemoryHardeningPersistence(),
        recorder=_AlternateRecorder(),
    ).runtime_instance_id

    assert second == first
    assert different != first

    hardening_runtime = importlib.import_module(
        "app.hardening.validation.runtime"
    )
    hardening_runtime = importlib.reload(hardening_runtime)
    restarted = hardening_runtime.HardeningRuntime(
        persistence=InMemoryHardeningPersistence()
    ).runtime_instance_id
    assert restarted == first


@pytest.mark.asyncio
async def test_hardening_audit_id_is_replay_stable_across_reload() -> None:
    request = ValidateLineageRequest(
        records=(("root", None), ("child", "root")),
        scope="phase-1",
        correlation_id="corr-phase-1",
        request_id="req-phase-1",
    )
    runtime = HardeningRuntime(persistence=InMemoryHardeningPersistence())
    await runtime.validate_lineage(request)
    first_audit = (await runtime.persistence.list_audits())[0].audit_id

    hardening_runtime = importlib.import_module(
        "app.hardening.validation.runtime"
    )
    hardening_runtime = importlib.reload(hardening_runtime)
    restarted = hardening_runtime.HardeningRuntime(
        persistence=InMemoryHardeningPersistence()
    )
    await restarted.validate_lineage(request)
    restarted_audit = (await restarted.persistence.list_audits())[0].audit_id

    different = hardening_runtime.HardeningRuntime(
        persistence=InMemoryHardeningPersistence()
    )
    await different.validate_lineage(
        ValidateLineageRequest(
            records=(("root", None), ("child", "root")),
            scope="phase-1-different",
            correlation_id="corr-phase-1",
            request_id="req-phase-1",
        )
    )
    different_audit = (await different.persistence.list_audits())[0].audit_id

    assert restarted_audit == first_audit
    assert different_audit != first_audit


@pytest.mark.asyncio
async def test_agent_execution_and_tool_ids_are_replay_stable() -> None:
    first = await _agent_runtime().execute(
        "ok",
        {"ticket": "A"},
        tenant_id="tenant-a",
        request_id="req-a",
        metadata={"dispatch_id": "dispatch-a", "session_id": "session-a"},
    )
    second = await _agent_runtime().execute(
        "ok",
        {"ticket": "A"},
        tenant_id="tenant-a",
        request_id="req-a",
        metadata={"dispatch_id": "dispatch-a", "session_id": "session-a"},
    )
    different = await _agent_runtime().execute(
        "ok",
        {"ticket": "B"},
        tenant_id="tenant-a",
        request_id="req-a",
        metadata={"dispatch_id": "dispatch-a", "session_id": "session-a"},
    )

    assert second.trace.runtime_instance_id == first.trace.runtime_instance_id
    assert second.trace.execution_id == first.trace.execution_id
    assert (
        second.tool_envelopes[0].trace.invocation_id
        == first.tool_envelopes[0].trace.invocation_id
    )
    assert different.trace.execution_id != first.trace.execution_id


@pytest.mark.asyncio
async def test_agent_execution_and_tool_ids_survive_module_reload() -> None:
    first = await _agent_runtime().execute(
        "ok",
        {"ticket": "A"},
        tenant_id="tenant-a",
        request_id="req-a",
        metadata={"dispatch_id": "dispatch-a", "session_id": "session-a"},
    )

    identity_mod = importlib.import_module("app.agents.identity")
    invoker_mod = importlib.import_module("app.agents.tools.invoker")
    session_mod = importlib.import_module("app.agents.tools.session")
    runtime_mod = importlib.import_module("app.agents.runtime.runtime")
    importlib.reload(identity_mod)
    invoker_mod = importlib.reload(invoker_mod)
    importlib.reload(session_mod)
    runtime_mod = importlib.reload(runtime_mod)

    restarted = await _agent_runtime(
        runtime_cls=runtime_mod.AgentRuntime,
        invoker_cls=invoker_mod.ToolInvoker,
    ).execute(
        "ok",
        {"ticket": "A"},
        tenant_id="tenant-a",
        request_id="req-a",
        metadata={"dispatch_id": "dispatch-a", "session_id": "session-a"},
    )

    assert restarted.trace.runtime_instance_id == first.trace.runtime_instance_id
    assert restarted.trace.execution_id == first.trace.execution_id
    assert (
        restarted.tool_envelopes[0].trace.invocation_id
        == first.tool_envelopes[0].trace.invocation_id
    )


@pytest.mark.asyncio
async def test_tool_invocation_ordinals_prevent_same_execution_collision() -> None:
    env = await _agent_runtime().execute(
        "double",
        {"ticket": "A"},
        tenant_id="tenant-a",
        request_id="req-a",
        metadata={"dispatch_id": "dispatch-a", "session_id": "session-a"},
    )

    invocation_ids = [tool.trace.invocation_id for tool in env.tool_envelopes]
    assert len(invocation_ids) == 2
    assert len(set(invocation_ids)) == 2
