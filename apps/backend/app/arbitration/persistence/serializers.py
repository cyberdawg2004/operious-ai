"""Runtime → persistence serialisation."""

from __future__ import annotations

from app.arbitration.contracts.results import ArbitrationResult
from app.arbitration.envelopes import ArbitrationEnvelope
from app.arbitration.persistence.records import (
    ArbitrationConflictRecord,
    ArbitrationDeadlockRecord,
    ArbitrationFindingRecord,
    ArbitrationRecord,
)


def result_to_record(result: ArbitrationResult) -> ArbitrationRecord:
    """Project an `ArbitrationResult` into an immutable record."""
    decision = result.decision
    prevailing = decision.prevailing_authority
    return ArbitrationRecord(
        evaluation_id=result.evaluation_id,
        chain_id=result.chain_id,
        case_id=result.case_id,
        runtime_instance_id=result.runtime_instance_id,
        sequence=result.sequence,
        outcome=decision.outcome,
        prevailing_authority_level=(
            prevailing.level if prevailing is not None else None
        ),
        prevailing_authority_source_substrate=(
            prevailing.source_substrate
            if prevailing is not None
            else None
        ),
        prevailing_authority_source_id=(
            prevailing.source_id if prevailing is not None else None
        ),
        prevailing_authority_verdict=(
            prevailing.verdict if prevailing is not None else None
        ),
        reason=result.reason,
        evaluator_names=tuple(result.evaluator_names),
        findings=tuple(
            ArbitrationFindingRecord(
                finding_id=f.finding_id,
                evaluator_name=f.evaluator_name,
                outcome_hint=f.outcome_hint,
                code=f.code,
                message=f.message,
                detected_at=f.detected_at,
                related_conflict_id=f.related_conflict_id,
                related_deadlock_witness_id=(
                    f.related_deadlock_witness_id
                ),
                authority=f.authority,
                metadata=dict(f.metadata),
            )
            for f in result.findings
        ),
        conflicts=tuple(
            ArbitrationConflictRecord(
                conflict_id=c.conflict_id,
                kind=c.kind,
                participants=tuple(c.participants),
                participant_authorities=tuple(
                    c.participant_authorities
                ),
                summary=c.summary,
                metadata=dict(c.metadata),
            )
            for c in result.conflicts
        ),
        deadlock_witnesses=tuple(
            ArbitrationDeadlockRecord(
                witness_id=w.witness_id,
                kind=w.kind,
                contributing_ids=tuple(w.contributing_ids),
                summary=w.summary,
                iteration_count=w.iteration_count,
                metadata=dict(w.metadata),
            )
            for w in result.deadlock_witnesses
        ),
        signal_count=result.signal_count,
        recommendation_count=result.recommendation_count,
        iteration_count=result.iteration_count,
        max_iterations=result.max_iterations,
        correlation_id=result.correlation_id,
        request_id=result.request_id,
        tenant_id=result.tenant_id,
        started_at=result.started_at,
        ended_at=result.ended_at,
        latency_ms=result.latency_ms,
        error=result.error,
        metadata=dict(result.metadata),
    )


def envelope_to_record(
    envelope: ArbitrationEnvelope,
) -> ArbitrationRecord | None:
    """Project a successful envelope into a record; ``None`` for failed."""
    if envelope.result is None:
        return None
    return result_to_record(envelope.result)


__all__ = ["result_to_record", "envelope_to_record"]
