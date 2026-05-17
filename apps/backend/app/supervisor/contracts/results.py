"""`ExecutionInspectionResult` — apex output of `SupervisorRuntime.inspect()`.

Pairs 1:1 with `SupervisorTrace`. The persistence layer's
`serializers.py` converts `(result, trace)` into the on-disk record
set.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from app.supervisor.contracts.decisions import SupervisorDecision
from app.supervisor.contracts.evaluations import QAEvaluation
from app.supervisor.enums import InspectionMode


@dataclass(frozen=True, slots=True)
class ExecutionInspectionResult:
    """The supervisor's complete inspection output.

    Attributes:
        inspection_id:        Stable identifier for this inspection.
        execution_id:         The execution that was inspected.
        runtime_instance_id:  Which `SupervisorRuntime` instance ran.
        correlation_id /
        request_id /
        tenant_id:             Lineage carried through from the request.
        inspection_mode:       `LIVE` or `REPLAY`.
        evaluations:           Per-evaluator outputs in sorted-name order.
        decision:              Apex supervisor verdict.
        started_at / ended_at: Wall-clock window.
        latency_ms:            Total inspection latency.
        metadata:              Free-form, propagated from request.
    """

    inspection_id: uuid.UUID
    execution_id: uuid.UUID
    runtime_instance_id: uuid.UUID
    correlation_id: uuid.UUID | None
    request_id: str | None
    tenant_id: str | None
    inspection_mode: InspectionMode
    evaluations: tuple[QAEvaluation, ...]
    decision: SupervisorDecision
    started_at: datetime
    ended_at: datetime
    latency_ms: float
    metadata: Mapping[str, Any] = field(default_factory=dict)


__all__ = ["ExecutionInspectionResult"]
