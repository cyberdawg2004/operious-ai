"""Transport contracts for the v1 arbitration read endpoints.

Mirrors :class:`ArbitrationRecord` plus its three nested record
types (Finding, Conflict, Deadlock) as frozen Pydantic schemas
with explicit ``from_record`` projections.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.arbitration.persistence import (
    ArbitrationConflictRecord,
    ArbitrationDeadlockRecord,
    ArbitrationFindingRecord,
    ArbitrationRecord,
)


class ArbitrationFindingSchema(BaseModel):
    model_config = ConfigDict(frozen=True)

    finding_id: str
    evaluator_name: str
    outcome_hint: str
    code: str
    message: str
    detected_at: str | None = None
    related_conflict_id: str | None = None
    related_deadlock_witness_id: str | None = None
    authority: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_record(
        cls, record: ArbitrationFindingRecord
    ) -> "ArbitrationFindingSchema":
        return cls(
            finding_id=str(record.finding_id),
            evaluator_name=record.evaluator_name,
            outcome_hint=record.outcome_hint.value,
            code=record.code,
            message=record.message,
            detected_at=(
                record.detected_at.isoformat()
                if record.detected_at is not None
                else None
            ),
            related_conflict_id=(
                str(record.related_conflict_id)
                if record.related_conflict_id is not None
                else None
            ),
            related_deadlock_witness_id=(
                str(record.related_deadlock_witness_id)
                if record.related_deadlock_witness_id is not None
                else None
            ),
            authority=(
                record.authority.value
                if record.authority is not None
                else None
            ),
            metadata=dict(record.metadata),
        )


class ArbitrationConflictSchema(BaseModel):
    model_config = ConfigDict(frozen=True)

    conflict_id: str
    kind: str
    participants: list[str] = Field(default_factory=list)
    participant_authorities: list[str] = Field(default_factory=list)
    summary: str
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_record(
        cls, record: ArbitrationConflictRecord
    ) -> "ArbitrationConflictSchema":
        return cls(
            conflict_id=str(record.conflict_id),
            kind=record.kind.value,
            participants=list(record.participants),
            participant_authorities=[
                a.value for a in record.participant_authorities
            ],
            summary=record.summary,
            metadata=dict(record.metadata),
        )


class ArbitrationDeadlockSchema(BaseModel):
    model_config = ConfigDict(frozen=True)

    witness_id: str
    kind: str
    contributing_ids: list[str] = Field(default_factory=list)
    summary: str
    iteration_count: int
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_record(
        cls, record: ArbitrationDeadlockRecord
    ) -> "ArbitrationDeadlockSchema":
        return cls(
            witness_id=str(record.witness_id),
            kind=record.kind.value,
            contributing_ids=list(record.contributing_ids),
            summary=record.summary,
            iteration_count=record.iteration_count,
            metadata=dict(record.metadata),
        )


class ArbitrationEvaluationResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    evaluation_id: str
    chain_id: str
    case_id: str
    runtime_instance_id: str
    sequence: int
    outcome: str
    prevailing_authority_level: str | None = None
    prevailing_authority_source_substrate: str | None = None
    prevailing_authority_source_id: str | None = None
    prevailing_authority_verdict: str | None = None
    reason: str
    evaluator_names: list[str] = Field(default_factory=list)
    findings: list[ArbitrationFindingSchema] = Field(default_factory=list)
    conflicts: list[ArbitrationConflictSchema] = Field(default_factory=list)
    deadlock_witnesses: list[ArbitrationDeadlockSchema] = Field(
        default_factory=list
    )
    signal_count: int
    recommendation_count: int
    iteration_count: int
    max_iterations: int
    correlation_id: str | None = None
    request_id: str | None = None
    tenant_id: str | None = None
    started_at: str
    ended_at: str
    latency_ms: float
    error: str | None = None
    governance_decision_id: str | None = None
    governance_chain_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_record(
        cls, record: ArbitrationRecord
    ) -> "ArbitrationEvaluationResponse":
        return cls(
            evaluation_id=str(record.evaluation_id),
            chain_id=str(record.chain_id),
            case_id=str(record.case_id),
            runtime_instance_id=str(record.runtime_instance_id),
            sequence=record.sequence,
            outcome=record.outcome.value,
            prevailing_authority_level=(
                record.prevailing_authority_level.value
                if record.prevailing_authority_level is not None
                else None
            ),
            prevailing_authority_source_substrate=(
                record.prevailing_authority_source_substrate
            ),
            prevailing_authority_source_id=(
                record.prevailing_authority_source_id
            ),
            prevailing_authority_verdict=(
                record.prevailing_authority_verdict
            ),
            reason=record.reason,
            evaluator_names=list(record.evaluator_names),
            findings=[
                ArbitrationFindingSchema.from_record(f)
                for f in record.findings
            ],
            conflicts=[
                ArbitrationConflictSchema.from_record(c)
                for c in record.conflicts
            ],
            deadlock_witnesses=[
                ArbitrationDeadlockSchema.from_record(d)
                for d in record.deadlock_witnesses
            ],
            signal_count=record.signal_count,
            recommendation_count=record.recommendation_count,
            iteration_count=record.iteration_count,
            max_iterations=record.max_iterations,
            correlation_id=record.correlation_id,
            request_id=record.request_id,
            tenant_id=record.tenant_id,
            started_at=record.started_at.isoformat(),
            ended_at=record.ended_at.isoformat(),
            latency_ms=record.latency_ms,
            error=record.error,
            governance_decision_id=(
                str(record.governance_decision_id)
                if record.governance_decision_id is not None
                else None
            ),
            governance_chain_id=record.governance_chain_id,
            metadata=dict(record.metadata),
        )


class ArbitrationEvaluationsPage(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[ArbitrationEvaluationResponse] = Field(default_factory=list)
    total: int


__all__ = [
    "ArbitrationConflictSchema",
    "ArbitrationDeadlockSchema",
    "ArbitrationEvaluationResponse",
    "ArbitrationEvaluationsPage",
    "ArbitrationFindingSchema",
]
