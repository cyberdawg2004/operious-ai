"""Pure-function serializers between runtime types and records.

* `result_to_record(result)`     — primary converter; pure.
* `envelope_to_record(envelope)` — convenience for the envelope
                                    path; ``None`` for failed
                                    envelopes (no result).

These are pure — no I/O, no side effects, no exceptions for normal
inputs. Replay-safety: serialisation is byte-stable for fixed
inputs.
"""

from __future__ import annotations

from app.coordination.policy.contracts.results import (
    CoordinationPolicyEvaluationResult,
)
from app.coordination.policy.envelopes import (
    CoordinationPolicyEnvelope,
)
from app.coordination.policy.models.escalation import (
    CoordinationPolicyEscalation,
)
from app.coordination.policy.models.findings import (
    CoordinationPolicyFinding,
)
from app.coordination.policy.models.restriction import (
    CoordinationPolicyRestriction,
)
from app.coordination.policy.persistence.records import (
    CoordinationPolicyEscalationRecord,
    CoordinationPolicyFindingRecord,
    CoordinationPolicyRecord,
    CoordinationPolicyRestrictionRecord,
)


def result_to_record(
    result: CoordinationPolicyEvaluationResult,
) -> CoordinationPolicyRecord:
    """Convert a `CoordinationPolicyEvaluationResult` into its record."""
    return CoordinationPolicyRecord(
        evaluation_id=str(result.evaluation_id),
        chain_id=str(result.chain_id),
        runtime_instance_id=str(result.runtime_instance_id),
        sequence=result.sequence,
        coordination_id=str(result.coordination_id),
        coordination_message_id=str(result.coordination_message_id),
        sender_id=result.sender_id,
        recipient_id=result.recipient_id,
        recipient_kind=result.recipient_kind,
        direction=_extract_direction(result),
        message_type=_extract_message_type(result),
        priority=_extract_priority(result),
        aggregate_decision=result.aggregate_decision.value,
        evaluator_names=tuple(result.evaluator_names),
        finding_count=len(result.findings),
        restriction_count=len(result.restrictions),
        escalation_count=len(result.escalations),
        correlation_id=(
            str(result.correlation_id)
            if result.correlation_id is not None
            else None
        ),
        parent_coordination_id=(
            str(result.parent_coordination_id)
            if result.parent_coordination_id is not None
            else None
        ),
        parent_message_id=(
            str(result.parent_message_id)
            if result.parent_message_id is not None
            else None
        ),
        request_id=result.request_id,
        tenant_id=result.tenant_id,
        started_at=result.started_at.isoformat(),
        ended_at=result.ended_at.isoformat(),
        latency_ms=result.latency_ms,
        reason=result.reason,
        error=result.error,
        findings=tuple(_finding_to_record(f) for f in result.findings),
        restrictions=tuple(
            _restriction_to_record(r) for r in result.restrictions
        ),
        escalations=tuple(
            _escalation_to_record(e) for e in result.escalations
        ),
        metadata=dict(result.metadata),
    )


def envelope_to_record(
    envelope: CoordinationPolicyEnvelope,
) -> CoordinationPolicyRecord | None:
    """Convert a successful envelope to a record; ``None`` if failed.

    Failed envelopes (no result) do not produce a record at the
    serialiser layer — the runtime persists a `FAILED` record itself
    when it has enough lineage to do so.
    """
    if envelope.result is None:
        return None
    return result_to_record(envelope.result)


# ─── Internal helpers ────────────────────────────────────────────────


def _finding_to_record(
    f: CoordinationPolicyFinding,
) -> CoordinationPolicyFindingRecord:
    from datetime import datetime, timezone

    detected = f.detected_at or datetime.now(timezone.utc)
    return CoordinationPolicyFindingRecord(
        finding_id=str(f.finding_id),
        evaluator_name=f.evaluator_name,
        scope=f.scope.value,
        decision=f.decision.value,
        code=f.code,
        message=f.message,
        policy_id=f.policy_id,
        rule_id=f.rule_id,
        detected_at=detected.isoformat(),
        restrictions=tuple(
            _restriction_to_record(r) for r in f.restrictions
        ),
        escalations=tuple(
            _escalation_to_record(e) for e in f.escalations
        ),
        metadata=dict(f.metadata),
    )


def _restriction_to_record(
    r: CoordinationPolicyRestriction,
) -> CoordinationPolicyRestrictionRecord:
    return CoordinationPolicyRestrictionRecord(
        kind=r.kind.value,
        target=r.target,
        reason=r.reason,
        policy_id=r.policy_id,
        rule_id=r.rule_id,
        value=dict(r.value),
        metadata=dict(r.metadata),
    )


def _escalation_to_record(
    e: CoordinationPolicyEscalation,
) -> CoordinationPolicyEscalationRecord:
    return CoordinationPolicyEscalationRecord(
        kind=e.kind.value,
        target=e.target,
        reason=e.reason,
        policy_id=e.policy_id,
        rule_id=e.rule_id,
        metadata=dict(e.metadata),
    )


def _extract_direction(
    result: CoordinationPolicyEvaluationResult,
) -> str:
    """Pull `direction` from result metadata; the result itself does
    not carry direction (the trace does). The runtime writes
    `coordination.direction` into the result metadata for record-
    layer convenience.
    """
    value = result.metadata.get("coordination.direction")
    return str(value) if value is not None else ""


def _extract_message_type(
    result: CoordinationPolicyEvaluationResult,
) -> str:
    value = result.metadata.get("coordination.message_type")
    return str(value) if value is not None else ""


def _extract_priority(
    result: CoordinationPolicyEvaluationResult,
) -> int:
    value = result.metadata.get("coordination.priority")
    try:
        return int(value) if value is not None else 0
    except (TypeError, ValueError):
        return 0


__all__ = [
    "result_to_record",
    "envelope_to_record",
]
