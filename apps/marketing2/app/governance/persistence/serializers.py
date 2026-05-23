"""Pure-function serializers between runtime types and records.

The functions here are **the boundary** between live runtime value
objects (`GovernanceDecision`, `GovernanceTrace`, `EnforcementAction`)
and the persistable record shapes. They are pure — no I/O, no
side-effects, no exceptions for normal inputs.

The serialisers are deliberately bidirectional where it matters:

* runtime → record       (`*_to_record`)
* record → runtime       (`record_to_*`) — only for the apex
                          `GovernanceDecision`, which is the type that
                          replay tools reconstruct most often.

Bidirectional `GovernanceTrace` reconstruction isn't shipped because
the trace records latency / timestamps that don't always round-trip
cleanly across timezone-naive backends; runtime traces should be
**produced**, not **reconstructed**, in normal flows.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from app.governance.decisions import GovernanceDecision, PolicyEvaluationResult
from app.governance.enforcement.models import EnforcementAction
from app.governance.enums import (
    Decision,
    EnforcementStage,
    RestrictionKind,
    ViolationSeverity,
)
from app.governance.persistence.records import (
    EnforcementActionRecord,
    GovernanceDecisionRecord,
    GovernanceTraceRecord,
    PolicyEvaluationTraceRecord,
    PolicyViolationRecord,
    RuntimeRestrictionRecord,
)
from app.governance.tracing import GovernanceTrace
from app.governance.value_objects import PolicyViolation, RuntimeRestriction


# ─── runtime → record ─────────────────────────────────────────────────


def decision_to_record(decision: GovernanceDecision) -> GovernanceDecisionRecord:
    """Convert a live `GovernanceDecision` into its persistable shape."""
    return GovernanceDecisionRecord(
        decision_id=str(decision.decision_id),
        decision=decision.decision.value,
        stage=decision.stage.value,
        policy_chain_id=decision.policy_chain_id,
        reason=decision.reason,
        decided_at=decision.decided_at.isoformat(),
        correlation_id=(
            str(decision.metadata.get("correlation_id"))
            if decision.metadata.get("correlation_id")
            else None
        ),
        violations=tuple(_violation_to_record(v) for v in decision.violations),
        restrictions=tuple(
            _restriction_to_record(r) for r in decision.restrictions
        ),
        metadata={
            k: v for k, v in decision.metadata.items() if k != "correlation_id"
        },
    )


def trace_to_record(trace: GovernanceTrace) -> GovernanceTraceRecord:
    return GovernanceTraceRecord(
        decision_id=str(trace.decision_id),
        request_id=trace.request_id,
        correlation_id=(
            str(trace.correlation_id) if trace.correlation_id is not None else None
        ),
        stage=trace.stage.value,
        action=trace.action,
        resource=trace.resource,
        actor=trace.actor,
        tenant_id=trace.tenant_id,
        subject_kind=trace.subject_kind,
        started_at=trace.started_at.isoformat(),
        ended_at=trace.ended_at.isoformat(),
        latency_ms=trace.latency_ms,
        status=trace.status,
        final_decision=trace.final_decision.value,
        policy_chain_id=trace.policy_chain_id,
        rule_count=trace.rule_count,
        violation_count=trace.violation_count,
        restriction_count=trace.restriction_count,
        enforcement_handler=trace.enforcement_handler,
        enforcement_status=trace.enforcement_status,
        enforcement_latency_ms=trace.enforcement_latency_ms,
        policy_traces=tuple(
            PolicyEvaluationTraceRecord(
                policy_name=pt.policy_name,
                status=pt.status,
                started_at=pt.started_at.isoformat(),
                ended_at=pt.ended_at.isoformat(),
                latency_ms=pt.latency_ms,
                rule_count=pt.rule_count,
                decision_counts={d.value: c for d, c in pt.decision_counts.items()},
                error=pt.error,
                metadata=dict(pt.metadata),
            )
            for pt in trace.policy_traces
        ),
        error=trace.error,
        metadata=dict(trace.metadata),
    )


def enforcement_action_to_record(
    action: EnforcementAction,
) -> EnforcementActionRecord:
    return EnforcementActionRecord(
        action_id=str(action.action_id),
        handler_name=action.handler_name,
        decision_id=str(action.decision_id),
        outcome=action.outcome.value,
        applied_at=action.applied_at.isoformat(),
        detail=action.detail,
        metadata=dict(action.metadata),
    )


# ─── record → runtime ─────────────────────────────────────────────────


def record_to_decision(record: GovernanceDecisionRecord) -> GovernanceDecision:
    """Reconstruct a `GovernanceDecision` from its record.

    Used by replay tools and audit-reconciliation utilities. Note:
    `evaluated_rules` is NOT persisted (the record only stores
    violations + restrictions for query density); the reconstructed
    decision's `evaluated_rules` field will be the violations cast back
    to results. This is sufficient for *verdict* replay but NOT for
    full per-rule introspection — that requires the corresponding
    `GovernanceTraceRecord` (which IS round-trippable into per-policy
    metadata).
    """
    decision_enum = Decision(record.decision)
    stage_enum = EnforcementStage(record.stage)
    metadata = dict(record.metadata)
    if record.correlation_id is not None:
        metadata["correlation_id"] = record.correlation_id

    # Reconstruct results from violations (lossy — see docstring).
    results = tuple(
        PolicyEvaluationResult(
            policy_name=v.policy_name,
            rule_id=v.rule_id,
            decision=Decision(v.decision),
            severity=ViolationSeverity(v.severity),
            reason=v.detail,
            metadata=dict(v.metadata),
        )
        for v in record.violations
    )

    return GovernanceDecision(
        decision_id=uuid.UUID(record.decision_id),
        decision=decision_enum,
        stage=stage_enum,
        policy_chain_id=record.policy_chain_id,
        evaluated_rules=results,
        violations=tuple(_record_to_violation(v) for v in record.violations),
        restrictions=tuple(_record_to_restriction(r) for r in record.restrictions),
        reason=record.reason,
        decided_at=datetime.fromisoformat(record.decided_at),
        metadata=metadata,
    )


# ─── Internal helpers ────────────────────────────────────────────────


def _violation_to_record(v: PolicyViolation) -> PolicyViolationRecord:
    return PolicyViolationRecord(
        policy_name=v.policy_name,
        rule_id=v.rule_id,
        decision=v.decision.value,
        severity=int(v.severity),
        detail=v.detail,
        metadata=dict(v.metadata),
    )


def _restriction_to_record(r: RuntimeRestriction) -> RuntimeRestrictionRecord:
    return RuntimeRestrictionRecord(
        kind=r.kind.value,
        target=r.target,
        value=r.value,
        reason=r.reason,
        policy_name=r.policy_name,
        rule_id=r.rule_id,
        metadata=dict(r.metadata),
    )


def _record_to_violation(record: PolicyViolationRecord) -> PolicyViolation:
    return PolicyViolation(
        policy_name=record.policy_name,
        rule_id=record.rule_id,
        decision=Decision(record.decision),
        severity=ViolationSeverity(record.severity),
        detail=record.detail,
        metadata=dict(record.metadata),
    )


def _record_to_restriction(record: RuntimeRestrictionRecord) -> RuntimeRestriction:
    return RuntimeRestriction(
        kind=RestrictionKind(record.kind),
        target=record.target,
        value=record.value,
        reason=record.reason,
        policy_name=record.policy_name,
        rule_id=record.rule_id,
        metadata=dict(record.metadata),
    )


__all__ = [
    "decision_to_record",
    "trace_to_record",
    "enforcement_action_to_record",
    "record_to_decision",
]
