"""Supervisor execution traces.

Two trace shapes:

* `EvaluatorTrace` — one per evaluator invocation.
* `SupervisorTrace` — one per `SupervisorRuntime.inspect()` call,
                       aggregates the evaluator traces.

Same discipline as `AgentExecutionTrace` / `GovernanceTrace`: frozen,
slotted, serializable via the persistence-layer record converters.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from app.supervisor.enums import (
    EvaluationStatus,
    InspectionMode,
    SupervisorDecisionKind,
)


@dataclass(frozen=True, slots=True)
class EvaluatorTrace:
    """One evaluator's execution record."""

    evaluator_name: str
    status: EvaluationStatus
    started_at: datetime
    ended_at: datetime
    latency_ms: float
    finding_count: int
    score: float
    error: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SupervisorTrace:
    """Apex trace for one inspection invocation.

    Carries everything a supervisor-runtime persistence backend needs
    to reconstruct the inspection for audit / replay. Pairs 1:1 with
    `ExecutionInspectionResult`.

    Wedge B6 adds ``tenant_authority_source`` so replay can audit
    WHICH input produced the effective ``tenant_id``. The field is
    optional (``None`` for pre-B6 records on round-trip) so existing
    persisted traces continue to deserialize unchanged.
    """

    inspection_id: uuid.UUID
    execution_id: uuid.UUID
    runtime_instance_id: uuid.UUID
    correlation_id: uuid.UUID | None
    request_id: str | None
    tenant_id: str | None
    inspection_mode: InspectionMode
    started_at: datetime
    ended_at: datetime
    latency_ms: float
    evaluator_traces: tuple[EvaluatorTrace, ...]
    decision_kind: SupervisorDecisionKind
    aggregate_score: float
    finding_count: int
    escalation_count: int
    error: str | None = None
    tenant_authority_source: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


__all__ = ["EvaluatorTrace", "SupervisorTrace"]
