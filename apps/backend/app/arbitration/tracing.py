"""Arbitration traces.

Two trace shapes — same discipline as every sibling substrate:

* `ArbitrationTraceContext` — identity bundle propagated into / out
                              of an evaluation.
* `ArbitrationTrace`        — one per
                              `OperationalArbitrationRuntime.evaluate()`
                              call. Pairs 1:1 with the
                              `ArbitrationResult`.

Both are frozen, slotted, replay-safe.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from app.arbitration.enums import ArbitrationOutcome
from app.arbitration.identity import (
    ArbitrationCaseId,
    ArbitrationChainId,
    ArbitrationEvaluationId,
)


@dataclass(frozen=True, slots=True)
class ArbitrationTraceContext:
    """Lineage identifiers propagated through an arbitration evaluation."""

    evaluation_id: ArbitrationEvaluationId
    chain_id: ArbitrationChainId
    case_id: ArbitrationCaseId
    correlation_id: str | None = None
    request_id: str | None = None
    tenant_id: str | None = None


@dataclass(frozen=True, slots=True)
class ArbitrationTrace:
    """Apex trace for one `OperationalArbitrationRuntime.evaluate()` call."""

    evaluation_id: ArbitrationEvaluationId
    chain_id: ArbitrationChainId
    case_id: ArbitrationCaseId
    runtime_instance_id: uuid.UUID
    sequence: int
    outcome: ArbitrationOutcome
    evaluator_names: tuple[str, ...]
    finding_count: int
    conflict_count: int
    deadlock_witness_count: int
    signal_count: int
    recommendation_count: int
    iteration_count: int
    max_iterations: int
    correlation_id: str | None
    request_id: str | None
    tenant_id: str | None
    started_at: datetime
    ended_at: datetime
    latency_ms: float
    error: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    tenant_authority_source: str | None = None


__all__ = ["ArbitrationTraceContext", "ArbitrationTrace"]
