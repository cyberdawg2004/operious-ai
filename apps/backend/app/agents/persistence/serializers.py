"""Pure functions converting runtime traces / envelopes into records.

Three converters:

* `tool_trace_to_record`        — `ToolInvocationTrace` → `ToolInvocationRecord`
* `execution_trace_to_record`   — `AgentExecutionTrace` → `AgentExecutionRecord`
* `execution_envelope_to_records` — `AgentExecutionEnvelope` →
                                    (execution_record, tool_records)

These are pure functions — no I/O, no global state. Repository
backends call them at write time; replay tools call them in reverse
via the records' `from_dict`.
"""

from __future__ import annotations

from app.agents.envelopes import AgentExecutionEnvelope
from app.agents.persistence.records import (
    AgentExecutionRecord,
    StateTransitionRecord,
    ToolInvocationRecord,
)
from app.agents.tracing import AgentExecutionTrace, ToolInvocationTrace


def tool_trace_to_record(trace: ToolInvocationTrace) -> ToolInvocationRecord:
    return ToolInvocationRecord(
        invocation_id=str(trace.invocation_id),
        execution_id=str(trace.execution_id),
        tool_name=trace.tool_name,
        status=trace.status.value,
        started_at=trace.started_at.isoformat(),
        ended_at=trace.ended_at.isoformat(),
        latency_ms=trace.latency_ms,
        governance_decision_id=(
            str(trace.governance_decision_id)
            if trace.governance_decision_id is not None
            else None
        ),
        error=trace.error,
        metadata=dict(trace.metadata),
    )


def execution_trace_to_record(
    trace: AgentExecutionTrace,
    *,
    tenant_id: str | None = None,
) -> AgentExecutionRecord:
    """Project an ``AgentExecutionTrace`` into its persistable record.

    Authority resolution: the optional ``tenant_id`` parameter, when
    supplied, overrides the trace's own ``tenant_id``. Otherwise the
    trace's typed ``tenant_id`` field is the canonical source.
    Metadata is NEVER consulted for tenant identity (Phase 1 / Wedge
    B3 closed the metadata-fishing path).
    """
    return AgentExecutionRecord(
        execution_id=str(trace.execution_id),
        runtime_instance_id=str(trace.runtime_instance_id),
        agent_id=trace.agent_id,
        correlation_id=(
            str(trace.correlation_id)
            if trace.correlation_id is not None
            else None
        ),
        parent_execution_id=(
            str(trace.parent_execution_id)
            if trace.parent_execution_id is not None
            else None
        ),
        parent_chain=tuple(str(x) for x in trace.parent_chain),
        request_id=trace.request_id,
        tenant_id=tenant_id if tenant_id is not None else trace.tenant_id,
        final_state=trace.final_state.value,
        started_at=trace.started_at.isoformat(),
        ended_at=trace.ended_at.isoformat(),
        latency_ms=trace.latency_ms,
        state_transitions=tuple(
            StateTransitionRecord(
                from_state=t.from_state.value,
                to_state=t.to_state.value,
                transitioned_at=t.transitioned_at.isoformat(),
                reason=t.reason,
            )
            for t in trace.state_transitions
        ),
        tool_invocation_count=trace.tool_invocation_count,
        tool_invocation_ids=tuple(str(x) for x in trace.tool_invocation_ids),
        governance_decision_ids=tuple(
            str(x) for x in trace.governance_decision_ids
        ),
        error=trace.error,
        metadata=dict(trace.metadata),
    )


def execution_envelope_to_records(
    envelope: AgentExecutionEnvelope,
    *,
    tenant_id: str | None = None,
) -> tuple[AgentExecutionRecord, tuple[ToolInvocationRecord, ...]]:
    """Decompose an envelope into the record set a backend persists.

    Returns the execution record + the ordered tool invocation
    records in one call. Backends can write atomically when
    supported.
    """
    execution_record = execution_trace_to_record(
        envelope.trace, tenant_id=tenant_id
    )
    tool_records = tuple(
        tool_trace_to_record(env.trace) for env in envelope.tool_envelopes
    )
    return execution_record, tool_records


__all__ = [
    "tool_trace_to_record",
    "execution_trace_to_record",
    "execution_envelope_to_records",
]
