"""Sprint J — agent runtime kernel tests.

Properties pinned:

* `AgentRuntime.execute` never raises; every outcome lands on an
  `AgentExecutionEnvelope`,
* successful execution drives CREATED → READY → RUNNING → COMPLETED,
* an agent that raises lands in FAILED with the error attached,
* an unknown agent_id produces a fast-fail FAILED envelope,
* tool envelopes captured by the session are folded into the
  execution envelope in invocation order,
* causality propagation: `parent_execution_id` + `parent_chain` are
  threaded into the trace and accumulate across nested executions,
* repeated executions of the same deterministic agent produce
  identical trace structure (state-transition sequence, tool count).
"""

from __future__ import annotations

import uuid
from typing import Any, ClassVar, Mapping

import pytest

from app.agents.capabilities import AgentCapability, CapabilitySet, ExecutionConstraints
from app.agents.context import AgentExecutionContext
from app.agents.enums import CapabilityScope, ExecutionState
from app.agents.results import (
    AgentExecutionResult,
    ToolInvocationRequest,
    ToolInvocationResult,
)
from app.agents.runtime import AgentRegistry, AgentRuntime, BaseAgent
from app.agents.tools import (
    AgentToolSession,
    BaseTool,
    ToolCapability,
    ToolInvoker,
    ToolRegistry,
)
from app.agents.value_objects import CausalityMetadata


# ─── Fixtures ────────────────────────────────────────────────────────


class _EchoTool(BaseTool):
    name: ClassVar[str] = "echo"
    capability: ClassVar[ToolCapability] = ToolCapability.READ_ONLY
    required_capabilities: ClassVar[frozenset[str]] = frozenset({"tool.echo"})

    async def invoke(
        self, request: ToolInvocationRequest, context: AgentExecutionContext
    ) -> ToolInvocationResult:
        return ToolInvocationResult(output=dict(request.payload))


class _RaisingTool(BaseTool):
    name: ClassVar[str] = "raiser"
    capability: ClassVar[ToolCapability] = ToolCapability.READ_ONLY
    required_capabilities: ClassVar[frozenset[str]] = frozenset({"tool.echo"})

    async def invoke(
        self, request: ToolInvocationRequest, context: AgentExecutionContext
    ) -> ToolInvocationResult:
        raise RuntimeError("tool exploded")


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


class _ToolRaisingAgent(BaseAgent):
    agent_id: ClassVar[str] = "tool_raises"
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
            ToolInvocationRequest(tool_name="raiser", payload={})
        )
        # The tool raised, but the session returns an envelope.
        # The agent decides what to do — here we report success
        # despite the failure so we can assert the runtime captures
        # the failed envelope without itself failing.
        return AgentExecutionResult(
            output={"tool_ok": env.is_ok, "error": str(env.error)}
        )


def _runtime() -> AgentRuntime:
    tools = ToolRegistry()
    tools.register(_EchoTool())
    tools.register(_RaisingTool())
    invoker = ToolInvoker(tool_registry=tools)
    agents = AgentRegistry()
    agents.register(_OkAgent())
    agents.register(_FailingAgent())
    agents.register(_ToolRaisingAgent())
    return AgentRuntime(agent_registry=agents, tool_invoker=invoker)


# ─── Happy-path tests ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_successful_execution_completes() -> None:
    rt = _runtime()
    env = await rt.execute("ok", {})
    assert env.is_ok
    assert env.error is None
    assert env.trace.final_state is ExecutionState.COMPLETED
    assert len(env.tool_envelopes) == 1
    assert env.tool_envelopes[0].is_ok
    assert env.result is not None
    assert env.result.output == {"echoed": {"v": 1}}


@pytest.mark.asyncio
async def test_state_transitions_recorded_in_order() -> None:
    rt = _runtime()
    env = await rt.execute("ok", {})
    transitions = env.trace.state_transitions
    assert len(transitions) == 3
    assert (transitions[0].from_state, transitions[0].to_state) == (
        ExecutionState.CREATED,
        ExecutionState.READY,
    )
    assert (transitions[1].from_state, transitions[1].to_state) == (
        ExecutionState.READY,
        ExecutionState.RUNNING,
    )
    assert (transitions[2].from_state, transitions[2].to_state) == (
        ExecutionState.RUNNING,
        ExecutionState.COMPLETED,
    )


@pytest.mark.asyncio
async def test_failing_agent_lands_in_failed_state() -> None:
    rt = _runtime()
    env = await rt.execute("boom", {})
    assert not env.is_ok
    assert env.error is not None
    assert env.trace.error is not None
    assert env.trace.final_state is ExecutionState.FAILED
    assert "agent exploded" in env.trace.error
    # Final transition is RUNNING → FAILED.
    last = env.trace.state_transitions[-1]
    assert (last.from_state, last.to_state) == (
        ExecutionState.RUNNING,
        ExecutionState.FAILED,
    )


@pytest.mark.asyncio
async def test_unknown_agent_fast_fails_without_raising() -> None:
    rt = _runtime()
    env = await rt.execute("not_registered", {})
    assert not env.is_ok
    assert env.error is not None
    assert "unknown agent" in str(env.error)
    assert env.trace.final_state is ExecutionState.FAILED
    assert env.trace.tool_invocation_count == 0


@pytest.mark.asyncio
async def test_tool_raising_inside_agent_does_not_fail_runtime() -> None:
    rt = _runtime()
    env = await rt.execute("tool_raises", {})
    # The agent itself returned a result, so the execution succeeded.
    assert env.is_ok
    assert env.trace.final_state is ExecutionState.COMPLETED
    assert env.trace.tool_invocation_count == 1
    # The tool envelope captured the raise.
    tool_env = env.tool_envelopes[0]
    assert not tool_env.is_ok
    assert tool_env.error is not None
    assert tool_env.trace.error is not None
    assert "tool exploded" in tool_env.trace.error


@pytest.mark.asyncio
async def test_governance_decision_ids_empty_without_governance() -> None:
    rt = _runtime()
    env = await rt.execute("ok", {})
    assert env.governance_envelopes == ()
    assert env.trace.governance_decision_ids == ()
    assert env.tool_envelopes[0].governance_envelope is None


# ─── Causality + lineage tests ──────────────────────────────────────


@pytest.mark.asyncio
async def test_causality_chain_extended_with_parent_execution_id() -> None:
    rt = _runtime()
    parent_id = uuid.uuid4()
    causality = CausalityMetadata(
        initiator="parent_runtime",
        cause="downstream",
        parent_chain=(uuid.uuid4(),),
    )
    env = await rt.execute(
        "ok",
        {},
        parent_execution_id=parent_id,
        causality=causality,
    )
    assert env.trace.parent_execution_id == parent_id
    # The runtime appends parent_execution_id to the chain.
    assert env.trace.parent_chain[-1] == parent_id
    assert len(env.trace.parent_chain) == 2


@pytest.mark.asyncio
async def test_causality_chain_not_duplicated_when_parent_already_present() -> None:
    rt = _runtime()
    parent_id = uuid.uuid4()
    causality = CausalityMetadata(parent_chain=(parent_id,))
    env = await rt.execute(
        "ok",
        {},
        parent_execution_id=parent_id,
        causality=causality,
    )
    assert env.trace.parent_chain == (parent_id,)


@pytest.mark.asyncio
async def test_correlation_id_threads_into_trace() -> None:
    rt = _runtime()
    correlation_id = uuid.uuid4()
    env = await rt.execute("ok", {}, correlation_id=correlation_id)
    assert env.trace.correlation_id == correlation_id


@pytest.mark.asyncio
async def test_request_id_threads_into_trace_when_passed() -> None:
    rt = _runtime()
    env = await rt.execute("ok", {}, request_id="req-1234")
    assert env.trace.request_id == "req-1234"


@pytest.mark.asyncio
async def test_runtime_instance_id_stable_across_executions() -> None:
    rt = _runtime()
    env1 = await rt.execute("ok", {}, request_id="req-1")
    env2 = await rt.execute("ok", {}, request_id="req-2")
    assert env1.trace.runtime_instance_id == env2.trace.runtime_instance_id
    assert env1.trace.execution_id != env2.trace.execution_id


# ─── Determinism tests ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_repeated_execution_produces_identical_trace_structure() -> None:
    rt = _runtime()
    envs = [await rt.execute("ok", {}) for _ in range(5)]
    structures = {
        (
            tuple(
                (t.from_state.value, t.to_state.value)
                for t in env.trace.state_transitions
            ),
            env.trace.final_state.value,
            env.trace.tool_invocation_count,
        )
        for env in envs
    }
    assert len(structures) == 1


@pytest.mark.asyncio
async def test_execution_ids_are_deterministic_for_identical_inputs() -> None:
    rt = _runtime()
    first = await rt.execute("ok", {}, request_id="req-1")
    second = await rt.execute("ok", {}, request_id="req-1")
    different = await rt.execute("ok", {}, request_id="req-2")
    assert second.trace.execution_id == first.trace.execution_id
    assert different.trace.execution_id != first.trace.execution_id


# ─── Constraint enforcement tests ────────────────────────────────────


@pytest.mark.asyncio
async def test_max_tool_invocations_enforced_by_session() -> None:
    rt = _runtime()
    # Override constraints to cap at 0 invocations.
    constraints = ExecutionConstraints(max_tool_invocations=1)

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
            await session.invoke(ToolInvocationRequest(tool_name="echo"))
            await session.invoke(ToolInvocationRequest(tool_name="echo"))
            return AgentExecutionResult(output={"count": session.invocation_count})

    rt._agents.register(_DoubleCallAgent())
    env = await rt.execute("double", {}, constraints=constraints)
    assert env.is_ok
    assert env.trace.tool_invocation_count == 2
    # Second invocation was denied for cap.
    second = env.tool_envelopes[1]
    assert second.is_denied
    assert second.trace.metadata["reason"] == "max_invocations_exceeded"


@pytest.mark.asyncio
async def test_capability_violation_denies_tool_call() -> None:
    rt = _runtime()
    # Override capabilities to NOT include tool.echo. _OkAgent
    # asserts on env.is_ok after invoking, so its own assertion
    # raises when the call is denied — the runtime captures that
    # raise as FAILED. The substrate-level invariant under test is
    # that the *tool envelope* is denied with the right reason.
    env = await rt.execute(
        "ok",
        {},
        capabilities=CapabilitySet(),
    )
    assert env.trace.final_state is ExecutionState.FAILED
    assert len(env.tool_envelopes) == 1
    tool_env = env.tool_envelopes[0]
    assert tool_env.is_denied
    assert tool_env.trace.metadata["reason"] == "capability_violation"
    assert tool_env.trace.governance_decision_id is None


@pytest.mark.asyncio
async def test_allowed_tools_whitelist_blocks_unlisted_tools() -> None:
    rt = _runtime()
    constraints = ExecutionConstraints(allowed_tools=("other_tool",))
    env = await rt.execute("ok", {}, constraints=constraints)
    tool_env = env.tool_envelopes[0]
    assert tool_env.is_denied
    assert tool_env.trace.metadata["reason"] == "constraint_blocked"


# ─── Wedge B3: tenant_id propagation invariants ─────────────────────


@pytest.mark.asyncio
async def test_tenant_id_rides_typed_trace_field_not_metadata() -> None:
    """Wedge B3 constitutional invariant.

    ``tenant_id`` MUST ride the typed ``AgentExecutionTrace.tenant_id``
    field. It MUST NOT be carried in the metadata dict — that path
    was the metadata-laundering authority drift the audit flagged.
    """
    rt = _runtime()
    env = await rt.execute("ok", {}, tenant_id="acme")
    assert env.trace.tenant_id == "acme"
    assert "tenant_id" not in env.trace.metadata, (
        "tenant_id leaked into trace.metadata; Wedge B3 closure broken"
    )


# ─── H-3: max_tool_invocations default cap ────────────────────────────────────


def test_execution_constraints_default_has_finite_cap() -> None:
    """ExecutionConstraints() must produce a positive max_tool_invocations (H-3).

    Before this fix the default was 0 (unlimited), allowing adversarially
    prompted agents to loop unboundedly.  The new default is
    _DEFAULT_MAX_TOOL_INVOCATIONS (50).
    """
    from app.agents.capabilities import ExecutionConstraints, _DEFAULT_MAX_TOOL_INVOCATIONS

    constraints = ExecutionConstraints()
    assert constraints.max_tool_invocations > 0, (
        "default ExecutionConstraints must have a finite cap, not 0 (unlimited)"
    )
    assert constraints.max_tool_invocations == _DEFAULT_MAX_TOOL_INVOCATIONS


def test_explicit_zero_cap_is_still_supported() -> None:
    """Callers that genuinely need no cap can still pass max_tool_invocations=0."""
    from app.agents.capabilities import ExecutionConstraints

    constraints = ExecutionConstraints(max_tool_invocations=0)
    assert constraints.max_tool_invocations == 0


@pytest.mark.asyncio
async def test_tenant_id_none_when_not_supplied() -> None:
    rt = _runtime()
    env = await rt.execute("ok", {})
    assert env.trace.tenant_id is None
    assert "tenant_id" not in env.trace.metadata


@pytest.mark.asyncio
async def test_fast_fail_envelope_carries_typed_tenant_id() -> None:
    """Wedge B3 also closed the fast-fail tenant-id drop site.

    Prior to B3, an unknown-agent fast-fail produced a tenant-less
    trace even when the caller supplied ``tenant_id``. The trace
    must now carry the supplied tenant_id even on fast-fail.
    """
    rt = _runtime()
    env = await rt.execute("nonexistent_agent", {}, tenant_id="acme")
    assert env.trace.final_state is ExecutionState.FAILED
    assert env.trace.tenant_id == "acme"
    assert "tenant_id" not in env.trace.metadata


@pytest.mark.asyncio
async def test_persistence_serializer_reads_tenant_from_typed_field() -> None:
    """Round-trip the trace through the persistence serializer.

    After B3, ``execution_trace_to_record`` reads ``trace.tenant_id``
    directly. Metadata is never consulted.
    """
    from app.agents.persistence.serializers import (
        execution_trace_to_record,
    )

    rt = _runtime()
    env = await rt.execute("ok", {}, tenant_id="acme")
    record = execution_trace_to_record(env.trace)
    assert record.tenant_id == "acme"


@pytest.mark.asyncio
async def test_persistence_serializer_override_still_wins() -> None:
    """Explicit ``tenant_id=`` override remains the strongest authority.

    Preserves backward compatibility with callers that pass an
    explicit override (``execution_envelope_to_records(env, tenant_id=…)``).
    """
    from app.agents.persistence.serializers import (
        execution_trace_to_record,
    )

    rt = _runtime()
    env = await rt.execute("ok", {}, tenant_id="acme")
    record = execution_trace_to_record(env.trace, tenant_id="override")
    assert record.tenant_id == "override"


@pytest.mark.asyncio
async def test_supervisor_view_reads_tenant_from_typed_field() -> None:
    """Live-envelope inspection view consumes the typed field.

    After B3, ``build_inspection_view_from_envelope`` reads
    ``trace.tenant_id`` directly. The metadata-fishing path and its
    ``_safe_str`` helper were removed.
    """
    from app.supervisor.runtime.view_builder import (
        build_inspection_view_from_envelope,
    )

    rt = _runtime()
    env = await rt.execute("ok", {}, tenant_id="acme")
    view = build_inspection_view_from_envelope(env)
    assert view.tenant_id == "acme"


@pytest.mark.asyncio
async def test_supervisor_view_override_still_wins() -> None:
    from app.supervisor.runtime.view_builder import (
        build_inspection_view_from_envelope,
    )

    rt = _runtime()
    env = await rt.execute("ok", {}, tenant_id="acme")
    view = build_inspection_view_from_envelope(env, tenant_id="override")
    assert view.tenant_id == "override"
