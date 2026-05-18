"""Trace value objects for the agent runtime.

Two trace shapes:

* `ToolInvocationTrace` — one per tool invocation attempt (incl.
  governance-denied attempts). Carries the governance decision id when
  one was produced, so cross-trace queries can join governance and
  agent records.

* `AgentExecutionTrace` — one per `AgentRuntime.execute()` call.
  Carries the full state-transition sequence, the count of tool
  invocations, the chain of governance decisions touched, and the
  causality lineage.

Both are `frozen=True, slots=True`, JSON-serialization-friendly via
the persistence-record converters in `persistence/`.

Why traces live separately from envelopes: traces are what
persistence and supervisor runtimes consume. Envelopes are the
runtime carrier that wraps traces + results + errors. The same trace
type is reachable both from a live envelope and from a stored record.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from app.agents.enums import ExecutionState, ToolInvocationStatus
from app.agents.value_objects import StateTransition


@dataclass(frozen=True, slots=True)
class ToolInvocationTrace:
    """Trace for one tool invocation attempt.

    Attributes:
        invocation_id:           UUID of THIS invocation. Unique even
                                 across denied / failed attempts.
        execution_id:            Parent execution id (joins back to
                                 the `AgentExecutionTrace`).
        tool_name:               Tool that was invoked (or attempted).
        status:                  `ok` (executed), `failed` (executed
                                 and raised), `denied` (governance or
                                 substrate blocked before execution).
        started_at / ended_at:   Wall-clock window.
        latency_ms:              Total invoker latency including
                                 governance evaluation.
        governance_decision_id:  Decision id when a governance
                                 evaluation ran. ``None`` when no
                                 governance runtime is configured or
                                 when the substrate denied before
                                 governance was consulted.
        error:                   Stringified error for `failed` /
                                 `denied`; ``None`` for `ok`.
        metadata:                Free-form; carries the deny-reason
                                 vocabulary string and structured
                                 tool-side context.
    """

    invocation_id: uuid.UUID
    execution_id: uuid.UUID
    tool_name: str
    status: ToolInvocationStatus
    started_at: datetime
    ended_at: datetime
    latency_ms: float
    governance_decision_id: uuid.UUID | None = None
    error: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AgentExecutionTrace:
    """Trace for one agent execution.

    Attributes:
        execution_id:           UUID of THIS execution.
        runtime_instance_id:    Runtime that produced this execution.
        agent_id:               Agent that ran.
        correlation_id:         Optional pipeline-level grouping.
        parent_execution_id:    Optional causality parent.
        parent_chain:           Full ancestor chain (oldest first).
                                Sourced from `CausalityMetadata`.
        request_id:             Platform-wide request id.
        tenant_id:              Typed tenant authority anchor. The
                                canonical source of tenant identity for
                                this execution. Persistence serialisers
                                and supervisor view builders read this
                                field directly; metadata MUST NOT be
                                used as a fallback authority channel
                                (see Phase 1 / Wedge B3).
        state_transitions:      Ordered, chronological state moves.
        final_state:            Last state reached. Always terminal
                                for completed traces.
        started_at / ended_at:  Wall-clock window.
        latency_ms:              Total execution latency.
        tool_invocation_count:  Number of tool invocations attempted.
        tool_invocation_ids:    UUIDs of every tool-invocation trace
                                produced under this execution
                                (preserves order).
        governance_decision_ids: Decision ids touched by this
                                execution (empty if no governance ran).
        error:                  Stringified error when `final_state`
                                is FAILED; ``None`` otherwise.
        metadata:                Free-form. Initiator + cause are
                                duplicated here from causality so
                                trace consumers don't need a second
                                lookup. tenant_id is NOT carried here
                                — it rides the typed ``tenant_id``
                                field above.
    """

    execution_id: uuid.UUID
    runtime_instance_id: uuid.UUID
    agent_id: str
    correlation_id: uuid.UUID | None
    parent_execution_id: uuid.UUID | None
    parent_chain: tuple[uuid.UUID, ...]
    request_id: str | None
    state_transitions: tuple[StateTransition, ...]
    final_state: ExecutionState
    started_at: datetime
    ended_at: datetime
    latency_ms: float
    tool_invocation_count: int
    tenant_id: str | None = None
    tool_invocation_ids: tuple[uuid.UUID, ...] = ()
    governance_decision_ids: tuple[uuid.UUID, ...] = ()
    error: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


__all__ = [
    "ToolInvocationTrace",
    "AgentExecutionTrace",
]
