"""Pure builders: live envelope / replay records → `InspectionView`.

Two entry points, one normalised output. The `SupervisorRuntime`
picks one based on the request shape; evaluators never see the
choice.

Both builders are **pure** — no I/O, no global state, no wall-clock
reads. The same inputs produce identical views every call. This is
the cornerstone of replay-safe inspection.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Iterable

from app.agents.enums import ExecutionState, ToolInvocationStatus
from app.agents.envelopes import (
    AgentExecutionEnvelope,
    ToolInvocationEnvelope,
)
from app.agents.persistence.records import (
    AgentExecutionRecord,
    ToolInvocationRecord,
)
from app.governance.decisions import (
    is_allow_decision,
    is_blocking_decision,
)
from app.governance.enums import Decision
from app.governance.envelopes import GovernanceEnvelope
from app.governance.persistence.records import GovernanceDecisionRecord
from app.supervisor.models.view import (
    GovernanceDecisionView,
    InspectionView,
    StateTransitionView,
    ToolInvocationView,
)


# ─── Live envelope → view ────────────────────────────────────────────


def build_inspection_view_from_envelope(
    envelope: AgentExecutionEnvelope,
    *,
    tenant_id: str | None = None,
) -> InspectionView:
    """Normalise a live `AgentExecutionEnvelope` into an `InspectionView`."""
    trace = envelope.trace

    transitions = tuple(
        StateTransitionView(
            from_state=t.from_state,
            to_state=t.to_state,
            transitioned_at=t.transitioned_at,
            reason=t.reason,
        )
        for t in trace.state_transitions
    )

    tools = tuple(
        _envelope_tool_view(env) for env in envelope.tool_envelopes
    )

    governance = tuple(
        _envelope_governance_view(env)
        for env in envelope.governance_envelopes
        if env.is_ok
    )

    # Authority resolution: the optional ``tenant_id`` parameter
    # overrides when supplied; otherwise the trace's typed
    # ``tenant_id`` field is the canonical source. Metadata is NOT
    # consulted (Phase 1 / Wedge B3 closed the metadata-fishing path).
    effective_tenant = tenant_id if tenant_id is not None else trace.tenant_id

    return InspectionView(
        execution_id=trace.execution_id,
        runtime_instance_id=trace.runtime_instance_id,
        agent_id=trace.agent_id,
        correlation_id=trace.correlation_id,
        parent_execution_id=trace.parent_execution_id,
        parent_chain=tuple(trace.parent_chain),
        request_id=trace.request_id,
        tenant_id=effective_tenant,
        final_state=trace.final_state,
        state_transitions=transitions,
        started_at=trace.started_at,
        ended_at=trace.ended_at,
        latency_ms=trace.latency_ms,
        error=trace.error,
        tool_invocations=tools,
        governance_decisions=governance,
        metadata=dict(trace.metadata),
    )


def _envelope_tool_view(env: ToolInvocationEnvelope) -> ToolInvocationView:
    t = env.trace
    return ToolInvocationView(
        invocation_id=t.invocation_id,
        execution_id=t.execution_id,
        tool_name=t.tool_name,
        status=t.status,
        started_at=t.started_at,
        ended_at=t.ended_at,
        latency_ms=t.latency_ms,
        governance_decision_id=t.governance_decision_id,
        error=t.error,
        metadata=dict(t.metadata),
    )


def _envelope_governance_view(env: GovernanceEnvelope) -> GovernanceDecisionView:
    assert env.decision is not None  # is_ok guarantee
    decision = env.decision
    return GovernanceDecisionView(
        decision_id=decision.decision_id,
        decision=decision.decision.value,
        stage=decision.stage.value,
        policy_chain_id=decision.policy_chain_id,
        is_blocking=decision.is_blocking,
        is_allow=decision.is_allow,
        violation_count=len(decision.violations),
        restriction_count=len(decision.restrictions),
        reason=decision.reason,
        decided_at=decision.decided_at,
        correlation_id=env.trace.correlation_id,
        metadata=dict(decision.metadata),
    )


# ─── Replay records → view ───────────────────────────────────────────


def build_inspection_view_from_records(
    *,
    execution: AgentExecutionRecord,
    tool_invocations: Iterable[ToolInvocationRecord] = (),
    governance_decisions: Iterable[GovernanceDecisionRecord] = (),
    tenant_id: str | None = None,
) -> InspectionView:
    """Normalise replay records into an `InspectionView`.

    The view's structure is identical to the live-envelope flow so
    evaluators are mode-blind.

    `tenant_id`, when supplied, overrides the recorded execution's
    `tenant_id`. This matches the live-mode override semantics in
    `build_inspection_view_from_envelope` and lets callers attach a
    pipeline-level tenancy at inspection time even when the original
    execution did not carry one.
    """
    transitions = tuple(
        StateTransitionView(
            from_state=ExecutionState(t.from_state),
            to_state=ExecutionState(t.to_state),
            transitioned_at=_parse_iso(t.transitioned_at),
            reason=t.reason,
        )
        for t in execution.state_transitions
    )

    tools = tuple(_record_tool_view(r) for r in tool_invocations)
    governance = tuple(_record_governance_view(r) for r in governance_decisions)

    effective_tenant = (
        tenant_id if tenant_id is not None else execution.tenant_id
    )

    return InspectionView(
        execution_id=_require_uuid(execution.execution_id),
        runtime_instance_id=_require_uuid(execution.runtime_instance_id),
        agent_id=execution.agent_id,
        correlation_id=_parse_uuid(execution.correlation_id),
        parent_execution_id=_parse_uuid(execution.parent_execution_id),
        parent_chain=tuple(
            _require_uuid(x) for x in execution.parent_chain
        ),
        request_id=execution.request_id,
        tenant_id=effective_tenant,
        final_state=ExecutionState(execution.final_state),
        state_transitions=transitions,
        started_at=_parse_iso(execution.started_at),
        ended_at=_parse_iso(execution.ended_at),
        latency_ms=execution.latency_ms,
        error=execution.error,
        tool_invocations=tools,
        governance_decisions=governance,
        metadata=dict(execution.metadata),
    )


def _record_tool_view(r: ToolInvocationRecord) -> ToolInvocationView:
    return ToolInvocationView(
        invocation_id=_require_uuid(r.invocation_id),
        execution_id=_require_uuid(r.execution_id),
        tool_name=r.tool_name,
        status=ToolInvocationStatus(r.status),
        started_at=_parse_iso(r.started_at),
        ended_at=_parse_iso(r.ended_at),
        latency_ms=r.latency_ms,
        governance_decision_id=_parse_uuid(r.governance_decision_id),
        error=r.error,
        metadata=dict(r.metadata),
    )


def _record_governance_view(
    r: GovernanceDecisionRecord,
) -> GovernanceDecisionView:
    # Consume the canonical governance vocabulary instead of inlining
    # a string set. If a future Decision enum value becomes blocking
    # (or stops being so), the replay path follows automatically and
    # cannot silently drift from the live path's `decision.is_blocking`.
    decision_value = r.decision
    decision_enum = Decision(decision_value)
    return GovernanceDecisionView(
        decision_id=_require_uuid(r.decision_id),
        decision=decision_value,
        stage=r.stage,
        policy_chain_id=r.policy_chain_id,
        is_blocking=is_blocking_decision(decision_enum),
        is_allow=is_allow_decision(decision_enum),
        violation_count=len(r.violations),
        restriction_count=len(r.restrictions),
        reason=r.reason,
        decided_at=_parse_iso(r.decided_at),
        correlation_id=_parse_uuid(r.correlation_id),
        metadata=dict(r.metadata),
    )


# ─── Pure parsing helpers ────────────────────────────────────────────


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _parse_uuid(value: str | None) -> uuid.UUID | None:
    if value is None:
        return None
    return uuid.UUID(value)


def _require_uuid(value: str) -> uuid.UUID:
    return uuid.UUID(value)


__all__ = [
    "build_inspection_view_from_envelope",
    "build_inspection_view_from_records",
]
