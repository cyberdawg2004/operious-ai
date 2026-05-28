"""Constitutional regression tests for Wedge B6 — supervisor singular
authority resolution.

The audit defect being closed (DR-3 from
``docs/identity/tenant-propagation-audit.md``): the supervisor
runtime coalesced ``request.tenant_id`` with ``view.tenant_id`` in
TWO places (main inspect + fail-fast) without recording which input
produced the effective tenant. Replay reconstruction could not
audit the attribution chain.

This file pins:

1. ``ExecutionInspectionRequest`` accepts the typed
   ``AuthorityContext`` field (Wedge B2 surface adopted by
   supervisor) and enforces the coexistence invariant when both
   ``authority`` and ``tenant_id`` are supplied.
2. The supervisor's authority resolution is SINGULAR — one
   resolution per inspection drives Result, Trace, and persistence
   Record. No site coalesces tenants independently.
3. The priority is DETERMINISTIC: typed_authority wins, then
   legacy_tenant, then observed_tenant, then NONE.
4. The supervisor stamps ``tenant_authority_source`` onto every
   inspection output (Result, Trace, Record) so replay reads the
   source without re-running resolution.
5. The fail-fast path uses the SAME resolution as the main path —
   the second coalescing site is closed.
6. Replay determinism is preserved for pre-B6 callers (no
   ``authority`` field): ``result.tenant_id`` is byte-identical to
   the pre-B6 ``request.tenant_id or view.tenant_id`` semantics.
7. Persistence round-trip: ``InspectionRecord`` carries
   ``tenant_authority_source`` and ``from_dict`` honours both
   pre-B6 (missing key → None) and post-B6 (explicit value)
   wire shapes.

Anyone who reintroduces an independent tenant coalescing site, or
drops the ``tenant_authority_source`` attribution, or weakens the
priority order, fails this file.
"""

from __future__ import annotations

import uuid
from typing import Any, ClassVar, Mapping

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
from app.agents.tools import (
    AgentToolSession,
    BaseTool,
    ToolCapability,
    ToolInvoker,
    ToolRegistry,
)
from app.identity import (
    AuthorityContext,
    AuthoritySource,
    TenantId,
)
from app.supervisor.contracts.requests import (
    ExecutionInspectionRequest,
)
from app.supervisor.evaluators.builtin import (
    ExecutionCompletionEvaluator,
    GovernanceComplianceEvaluator,
    StateMachineHealthEvaluator,
    ToolInvocationEvaluator,
)
from app.supervisor.evaluators.registry import EvaluatorRegistry
from app.supervisor.persistence.records import InspectionRecord
from app.supervisor.persistence.serializers import (
    inspection_result_to_records,
)
from app.supervisor.runtime.runtime import SupervisorRuntime


# ─── Fixtures (minimal — only what B6 needs) ─────────────────────────


class _EchoTool(BaseTool):
    name: ClassVar[str] = "echo"
    capability: ClassVar[ToolCapability] = ToolCapability.READ_ONLY
    required_capabilities: ClassVar[frozenset[str]] = frozenset(
        {"tool.echo"}
    )

    async def invoke(
        self,
        request: ToolInvocationRequest,
        context: AgentExecutionContext,
    ) -> ToolInvocationResult:
        return ToolInvocationResult(output=dict(request.payload))


class _OkAgent(BaseAgent):
    agent_id: ClassVar[str] = "ok"
    declared_capabilities: ClassVar[
        tuple[AgentCapability, ...]
    ] = (
        AgentCapability(
            name="tool.echo", scope=CapabilityScope.INVOKE
        ),
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


def _build_agent_runtime() -> AgentRuntime:
    tool_registry = ToolRegistry()
    tool_registry.register(_EchoTool())
    agent_registry = AgentRegistry()
    agent_registry.register(_OkAgent())
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


# ─── ExecutionInspectionRequest typed-ingress surface ────────────────


def test_request_authority_defaults_to_none() -> None:
    """Legacy callers (no ``authority``) must keep working."""
    req = ExecutionInspectionRequest(execution_id=uuid.uuid4())
    assert req.authority is None
    assert req.tenant_id is None


def test_request_accepts_authority_alone() -> None:
    """Typed-only ingress path."""
    authority = AuthorityContext(tenant_id=TenantId("acme"))
    req = ExecutionInspectionRequest(
        execution_id=uuid.uuid4(), authority=authority
    )
    assert req.authority is authority
    assert req.tenant_id is None


def test_request_accepts_agreeing_authority_and_tenant_id() -> None:
    req = ExecutionInspectionRequest(
        execution_id=uuid.uuid4(),
        tenant_id="acme",
        authority=AuthorityContext(tenant_id=TenantId("acme")),
    )
    assert req.tenant_id == "acme"
    assert req.authority is not None
    assert req.authority.tenant_id == "acme"


def test_request_rejects_disagreeing_authority_and_tenant_id() -> None:
    """The Wedge B2 coexistence invariant adopted by supervisor."""
    with pytest.raises(
        ValueError,
        match="ExecutionInspectionRequest.*must agree",
    ):
        ExecutionInspectionRequest(
            execution_id=uuid.uuid4(),
            tenant_id="acme",
            authority=AuthorityContext(tenant_id=TenantId("beta")),
        )


def test_request_silent_when_authority_tenant_id_is_none() -> None:
    """``authority.tenant_id=None`` does NOT conflict with a non-None
    legacy ``tenant_id``."""
    req = ExecutionInspectionRequest(
        execution_id=uuid.uuid4(),
        tenant_id="acme",
        authority=AuthorityContext(),
    )
    assert req.tenant_id == "acme"
    assert req.authority is not None
    assert req.authority.tenant_id is None


# ─── Singular authority resolution at runtime ────────────────────────


@pytest.mark.asyncio
async def test_typed_authority_wins_over_observed() -> None:
    """When ``request.authority.tenant_id`` is supplied, it wins over
    the observed ``trace.tenant_id`` at supervisor resolution."""
    runtime = _build_agent_runtime()
    supervisor = _build_supervisor()
    envelope = await runtime.execute("ok", {}, tenant_id="observed-t")

    inspection = await supervisor.inspect(
        ExecutionInspectionRequest(
            execution_id=envelope.trace.execution_id,
            live_envelope=envelope,
            authority=AuthorityContext(
                tenant_id=TenantId("typed-t")
            ),
        )
    )
    assert inspection.is_ok
    result = inspection.unwrap()
    assert result.tenant_id == "typed-t"
    assert (
        result.tenant_authority_source
        == AuthoritySource.TYPED_AUTHORITY.value
    )


@pytest.mark.asyncio
async def test_legacy_tenant_wins_over_observed_when_no_typed() -> (
    None
):
    """Pre-B2 callers (no ``authority``): legacy ``tenant_id`` field
    is canonical, observed is the fallback. Replay-deterministic
    against pre-B6 semantics."""
    runtime = _build_agent_runtime()
    supervisor = _build_supervisor()
    envelope = await runtime.execute("ok", {}, tenant_id="observed-t")

    inspection = await supervisor.inspect(
        ExecutionInspectionRequest(
            execution_id=envelope.trace.execution_id,
            live_envelope=envelope,
            tenant_id="legacy-t",
        )
    )
    assert inspection.is_ok
    result = inspection.unwrap()
    assert result.tenant_id == "legacy-t"
    assert (
        result.tenant_authority_source
        == AuthoritySource.LEGACY_TENANT.value
    )


@pytest.mark.asyncio
async def test_observed_tenant_wins_when_nothing_else_supplied() -> (
    None
):
    """Pre-B6 fallback semantics are preserved: when no caller
    authority is supplied, the observed ``trace.tenant_id`` is the
    resolved authority."""
    runtime = _build_agent_runtime()
    supervisor = _build_supervisor()
    envelope = await runtime.execute("ok", {}, tenant_id="observed-t")

    inspection = await supervisor.inspect(
        ExecutionInspectionRequest(
            execution_id=envelope.trace.execution_id,
            live_envelope=envelope,
        )
    )
    assert inspection.is_ok
    result = inspection.unwrap()
    assert result.tenant_id == "observed-t"
    assert (
        result.tenant_authority_source
        == AuthoritySource.OBSERVED_TENANT.value
    )


@pytest.mark.asyncio
async def test_none_when_no_axis_carries_authority() -> None:
    """Fully-tenantless execution + tenantless inspection request:
    the resolution is NONE and the source records that."""
    runtime = _build_agent_runtime()
    supervisor = _build_supervisor()
    envelope = await runtime.execute("ok", {})  # no tenant_id

    inspection = await supervisor.inspect(
        ExecutionInspectionRequest(
            execution_id=envelope.trace.execution_id,
            live_envelope=envelope,
        )
    )
    assert inspection.is_ok
    result = inspection.unwrap()
    assert result.tenant_id is None
    assert (
        result.tenant_authority_source
        == AuthoritySource.NONE.value
    )


@pytest.mark.asyncio
async def test_result_and_trace_share_singular_resolution() -> None:
    """The Result and Trace must stamp the SAME resolved tenant_id
    AND the SAME source — no independent coalescing site."""
    runtime = _build_agent_runtime()
    supervisor = _build_supervisor()
    envelope = await runtime.execute("ok", {}, tenant_id="observed-t")

    inspection = await supervisor.inspect(
        ExecutionInspectionRequest(
            execution_id=envelope.trace.execution_id,
            live_envelope=envelope,
            tenant_id="legacy-t",
        )
    )
    assert inspection.is_ok
    result = inspection.unwrap()
    trace = inspection.trace
    assert result.tenant_id == trace.tenant_id
    assert (
        result.tenant_authority_source
        == trace.tenant_authority_source
    )
    assert (
        trace.tenant_authority_source
        == AuthoritySource.LEGACY_TENANT.value
    )


# ─── Fail-fast path consumes the SAME resolution ─────────────────────


@pytest.mark.asyncio
async def test_fail_fast_carries_typed_authority_source() -> None:
    """When request validation fails, the fail-fast envelope's trace
    must carry the same resolution that the main path would have
    produced. The audit-flagged second coalescing site is closed."""
    supervisor = _build_supervisor()
    inspection = await supervisor.inspect(
        ExecutionInspectionRequest(
            execution_id=uuid.uuid4(),
            authority=AuthorityContext(
                tenant_id=TenantId("typed-t")
            ),
        )
    )
    assert not inspection.is_ok
    trace = inspection.trace
    assert trace.tenant_id == "typed-t"
    assert (
        trace.tenant_authority_source
        == AuthoritySource.TYPED_AUTHORITY.value
    )


@pytest.mark.asyncio
async def test_fail_fast_carries_legacy_tenant_source() -> None:
    supervisor = _build_supervisor()
    inspection = await supervisor.inspect(
        ExecutionInspectionRequest(
            execution_id=uuid.uuid4(),
            tenant_id="legacy-t",
        )
    )
    assert not inspection.is_ok
    trace = inspection.trace
    assert trace.tenant_id == "legacy-t"
    assert (
        trace.tenant_authority_source
        == AuthoritySource.LEGACY_TENANT.value
    )


@pytest.mark.asyncio
async def test_fail_fast_carries_none_source_when_tenantless() -> (
    None
):
    supervisor = _build_supervisor()
    inspection = await supervisor.inspect(
        ExecutionInspectionRequest(execution_id=uuid.uuid4())
    )
    assert not inspection.is_ok
    trace = inspection.trace
    assert trace.tenant_id is None
    assert (
        trace.tenant_authority_source
        == AuthoritySource.NONE.value
    )


# ─── Persistence round-trip ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_persistence_round_trip_preserves_authority_source() -> (
    None
):
    """``InspectionRecord`` must carry the authority source through
    ``to_dict``/``from_dict``."""
    runtime = _build_agent_runtime()
    supervisor = _build_supervisor()
    envelope = await runtime.execute("ok", {}, tenant_id="observed-t")
    inspection = await supervisor.inspect(
        ExecutionInspectionRequest(
            execution_id=envelope.trace.execution_id,
            live_envelope=envelope,
            authority=AuthorityContext(
                tenant_id=TenantId("typed-t")
            ),
        )
    )
    assert inspection.is_ok
    result = inspection.unwrap()
    record_set = inspection_result_to_records(result)
    record = record_set.inspection
    assert (
        record.tenant_authority_source
        == AuthoritySource.TYPED_AUTHORITY.value
    )

    wire = record.to_dict()
    assert (
        wire["tenant_authority_source"]
        == AuthoritySource.TYPED_AUTHORITY.value
    )
    reconstructed = InspectionRecord.from_dict(wire)
    assert reconstructed == record


def test_persistence_backward_compat_pre_b6_record_missing_key() -> (
    None
):
    """Pre-Wedge-B6 records do not carry the
    ``tenant_authority_source`` key. ``from_dict`` must accept them
    and produce ``None`` on that axis without raising."""
    pre_b6_wire = {
        "inspection_id": str(uuid.uuid4()),
        "execution_id": str(uuid.uuid4()),
        "runtime_instance_id": str(uuid.uuid4()),
        "correlation_id": None,
        "request_id": None,
        "tenant_id": "acme",
        # NOTE: no tenant_authority_source key — this is the pre-B6
        # wire shape that on-disk records may have if the system is
        # ever deployed prior to B6 adoption.
        "inspection_mode": "live",
        "decision": {
            "decision_id": str(uuid.uuid4()),
            "kind": "accept",
            "aggregate_score": 1.0,
            "finding_ids": [],
            "escalation_ids": [],
            "reason": "",
            "decided_at": "2025-01-01T00:00:00+00:00",
            "metadata": {},
        },
        "evaluator_names": [],
        "started_at": "2025-01-01T00:00:00+00:00",
        "ended_at": "2025-01-01T00:00:00+00:00",
        "latency_ms": 0.0,
        "error": None,
        "metadata": {},
    }
    record = InspectionRecord.from_dict(pre_b6_wire)
    assert record.tenant_id == "acme"
    assert record.tenant_authority_source is None


# ─── No-orchestration-mutation invariant ─────────────────────────────


def test_supervisor_does_not_import_orchestration_paths() -> None:
    """B6 scope discipline: the supervisor consumes
    ``AuthorityContext`` from ``app.identity`` (a leaf substrate) —
    NOT from any orchestration substrate. The runtime is supervisor-
    internal; no agents / governance / coordination / arbitration
    runtime calls were added."""
    import pathlib

    supervisor_root = pathlib.Path(
        __file__
    ).parent.parent / "app" / "supervisor"
    forbidden = (
        "app.governance.runtime",
        "app.agents.runtime",
        "app.coordination.runtime",
        "app.arbitration.runtime",
    )
    for py_file in supervisor_root.rglob("*.py"):
        text = py_file.read_text(encoding="utf-8")
        for f in forbidden:
            assert f"from {f}" not in text, (
                f"{py_file} imports orchestration runtime {f}; "
                "Wedge B6 must remain supervisor-internal"
            )
