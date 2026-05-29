"""`InspectionView` — the normalised read-only shape evaluators consume.

Live envelopes and replay records carry the same logical information
in different shapes (Python value objects vs. record dataclasses).
The supervisor runtime normalises both into an `InspectionView`
before any evaluator runs; evaluators read `InspectionView` only.

Why a separate view type instead of having evaluators branch:

1. Determinism — both code paths land in the same shape so evaluator
   behaviour is identical regardless of source.
2. Auditability — the supervisor logs `inspection_mode` once on the
   trace, and the rest of the pipeline is mode-blind.
3. Forward portability — adding a third input source (e.g. an audit
   bus) becomes a new view-builder function, not a new evaluator
   branch.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.agents.enums import ExecutionState, ToolInvocationStatus


@dataclass(frozen=True, slots=True)
class StateTransitionView:
    """One state transition, materialised as plain types."""

    from_state: ExecutionState
    to_state: ExecutionState
    transitioned_at: datetime
    reason: str = ""


@dataclass(frozen=True, slots=True)
class ToolInvocationView:
    """One tool-invocation outcome in normalised form."""

    invocation_id: uuid.UUID
    execution_id: uuid.UUID
    tool_name: str
    status: ToolInvocationStatus
    started_at: datetime
    ended_at: datetime
    latency_ms: float
    governance_decision_id: uuid.UUID | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict[str, Any])


@dataclass(frozen=True, slots=True)
class GovernanceDecisionView:
    """One governance-decision outcome in normalised form.

    Carries the *minimum* fields supervisors need to reason about a
    governance verdict. The full decision body lives in governance
    persistence; the supervisor only inspects what's necessary.
    """

    decision_id: uuid.UUID
    decision: str            # "allow" | "deny" | "escalate" | …
    stage: str
    policy_chain_id: str
    is_blocking: bool
    is_allow: bool
    violation_count: int
    restriction_count: int
    reason: str
    decided_at: datetime
    correlation_id: uuid.UUID | None = None
    metadata: dict[str, Any] = field(default_factory=dict[str, Any])


@dataclass(frozen=True, slots=True)
class InspectionView:
    """The normalised read-only view evaluators consume.

    Every evaluator method receives one `InspectionView`. The view is
    built once per `SupervisorRuntime.inspect()` call by the pure
    function `runtime.view_builder.build_inspection_view`.
    """

    execution_id: uuid.UUID
    runtime_instance_id: uuid.UUID
    agent_id: str
    correlation_id: uuid.UUID | None
    parent_execution_id: uuid.UUID | None
    parent_chain: tuple[uuid.UUID, ...]
    request_id: str | None
    tenant_id: str | None
    final_state: ExecutionState
    state_transitions: tuple[StateTransitionView, ...]
    started_at: datetime
    ended_at: datetime
    latency_ms: float
    error: str | None
    tool_invocations: tuple[ToolInvocationView, ...]
    governance_decisions: tuple[GovernanceDecisionView, ...]
    metadata: dict[str, Any] = field(default_factory=dict[str, Any])


__all__ = [
    "StateTransitionView",
    "ToolInvocationView",
    "GovernanceDecisionView",
    "InspectionView",
]
