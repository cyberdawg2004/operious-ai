"""`ArbitrationResult` — apex output of `evaluate()`.

Pairs 1:1 with `ArbitrationTrace`. The persistence layer's
serialisers convert `(result, trace)` into the
`ArbitrationRecord`.

Determinism contract:

* `findings` preserves evaluator-sort order, then per-evaluator
  emission order.
* `conflicts` preserves emission order.
* `deadlock_witnesses` preserves emission order.
* `decision.outcome` is computed via deterministic aggregation —
  most-authoritative wins, never voting.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from app.arbitration.identity import (
    ArbitrationCaseId,
    ArbitrationChainId,
    ArbitrationEvaluationId,
)
from app.arbitration.models.conflict import ArbitrationConflict
from app.arbitration.models.deadlock import DeadlockWitness
from app.arbitration.models.decision import ArbitrationDecision
from app.arbitration.models.findings import ArbitrationFinding


@dataclass(frozen=True, slots=True)
class ArbitrationResult:
    """Apex result of one arbitration evaluation.

    Attributes:
        evaluation_id:        Stable identifier of THIS evaluation.
        chain_id:             Stable identifier of the evaluator-
                               chain composition that ran.
        case_id:              The arbitrated case's identifier.
        runtime_instance_id:  Stable id of the
                               `OperationalArbitrationRuntime`
                               instance.
        sequence:             Monotonic per-runtime-instance ordering.
        decision:             Apex interpretive decision.
        findings:             All findings, in evaluator-sort then
                               emission order.
        conflicts:            All detected conflicts.
        deadlock_witnesses:   All emitted deadlock witnesses.
        evaluator_names:      Names of evaluators that contributed.
        signal_count /
        recommendation_count: Mirrored from the case for audit.
        iteration_count /
        max_iterations:       Mirrored from the case.
        reason:               Short human-readable rationale.
        started_at / ended_at:Wall-clock window.
        latency_ms:           Total evaluation latency.
        correlation_id /
        request_id /
        tenant_id:            Lineage handles.
        error:                Set when the framework itself failed.
        metadata:             Free-form, propagated from request.
    """

    evaluation_id: ArbitrationEvaluationId
    chain_id: ArbitrationChainId
    case_id: ArbitrationCaseId
    runtime_instance_id: uuid.UUID
    sequence: int
    decision: ArbitrationDecision
    findings: tuple[ArbitrationFinding, ...]
    conflicts: tuple[ArbitrationConflict, ...]
    deadlock_witnesses: tuple[DeadlockWitness, ...]
    evaluator_names: tuple[str, ...]
    signal_count: int
    recommendation_count: int
    iteration_count: int
    max_iterations: int
    reason: str
    started_at: datetime
    ended_at: datetime
    latency_ms: float
    correlation_id: str | None = None
    request_id: str | None = None
    tenant_id: str | None = None
    error: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def outcome(self):  # type: ignore[no-untyped-def]
        return self.decision.outcome

    @property
    def is_resolved(self) -> bool:
        return self.decision.is_resolved

    @property
    def is_deadlock(self) -> bool:
        return self.decision.is_deadlock

    @property
    def is_conflict(self) -> bool:
        return self.decision.is_conflict

    @property
    def is_inconclusive(self) -> bool:
        return self.decision.is_inconclusive


__all__ = ["ArbitrationResult"]
