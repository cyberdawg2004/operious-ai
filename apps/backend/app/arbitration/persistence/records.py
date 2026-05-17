"""Persistence records — frozen, slotted, JSON-serializable shapes.

The records are the canonical wire format for arbitration audit.
Once persisted, a record's fields are immutable. The
`InMemoryArbitrationPersistence` and any future durable backend
enforce write-once at the protocol layer.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from app.arbitration.enums import (
    ArbitrationAuthorityLevel,
    ArbitrationConflictKind,
    ArbitrationDeadlockKind,
    ArbitrationOutcome,
)
from app.arbitration.identity import (
    ArbitrationCaseId,
    ArbitrationChainId,
    ArbitrationConflictId,
    ArbitrationEvaluationId,
)


@dataclass(frozen=True, slots=True)
class ArbitrationFindingRecord:
    """Persistence shape of one finding."""

    finding_id: uuid.UUID
    evaluator_name: str
    outcome_hint: ArbitrationOutcome
    code: str
    message: str
    detected_at: datetime | None
    related_conflict_id: ArbitrationConflictId | None
    related_deadlock_witness_id: uuid.UUID | None
    authority: ArbitrationAuthorityLevel | None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ArbitrationConflictRecord:
    """Persistence shape of one detected conflict."""

    conflict_id: ArbitrationConflictId
    kind: ArbitrationConflictKind
    participants: tuple[str, ...]
    participant_authorities: tuple[ArbitrationAuthorityLevel, ...]
    summary: str
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ArbitrationDeadlockRecord:
    """Persistence shape of one deadlock witness."""

    witness_id: uuid.UUID
    kind: ArbitrationDeadlockKind
    contributing_ids: tuple[str, ...]
    summary: str
    iteration_count: int
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ArbitrationRecord:
    """Persistence shape of one apex arbitration evaluation."""

    evaluation_id: ArbitrationEvaluationId
    chain_id: ArbitrationChainId
    case_id: ArbitrationCaseId
    runtime_instance_id: uuid.UUID
    sequence: int
    outcome: ArbitrationOutcome
    prevailing_authority_level: ArbitrationAuthorityLevel | None
    prevailing_authority_source_substrate: str | None
    prevailing_authority_source_id: str | None
    prevailing_authority_verdict: str | None
    reason: str
    evaluator_names: tuple[str, ...]
    findings: tuple[ArbitrationFindingRecord, ...]
    conflicts: tuple[ArbitrationConflictRecord, ...]
    deadlock_witnesses: tuple[ArbitrationDeadlockRecord, ...]
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
    error: str | None
    metadata: Mapping[str, Any] = field(default_factory=dict)


__all__ = [
    "ArbitrationConflictRecord",
    "ArbitrationDeadlockRecord",
    "ArbitrationFindingRecord",
    "ArbitrationRecord",
]
