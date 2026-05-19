"""Transport contracts for the v1 governance read endpoints.

Pure Pydantic schemas mirroring the persistable record shapes in
:mod:`app.governance.persistence.records`. Each schema is FROZEN
and provides an explicit ``from_record`` classmethod so the
projection from substrate record → wire shape is a single,
reviewable surface.

The schemas mirror the record shapes 1:1 except for ID
normalisation (records use stringified UUIDs already; schemas
keep them as strings for JSON wire fidelity). Nested
``violations`` / ``restrictions`` / ``evaluated_rules`` are
mirrored as nested Pydantic schemas rather than ``dict[str, Any]``
so the wire contract is strongly typed end-to-end.

Doctrine reminders:

* No imports from ``app.db.*`` — schemas never carry ORM types.
* No imports from ``app.services.*`` — schemas never depend on
  orchestration.
* Conversion FROM the substrate record happens via the explicit
  ``from_record`` classmethods only.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.governance.persistence import (
    GovernanceDecisionRecord,
    GovernanceTraceRecord,
)
from app.governance.persistence.records import (
    PolicyEvaluationResultRecord,
    PolicyEvaluationTraceRecord,
    PolicyViolationRecord,
    RuntimeRestrictionRecord,
)


# ─── Nested schemas ──────────────────────────────────────────────────────


class PolicyEvaluationResultSchema(BaseModel):
    """Wire mirror of :class:`PolicyEvaluationResultRecord`."""

    model_config = ConfigDict(frozen=True)

    policy_name: str
    rule_id: str
    decision: str
    severity: int
    reason: str
    evaluated_at: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    policy_version: str

    @classmethod
    def from_record(
        cls, record: PolicyEvaluationResultRecord
    ) -> "PolicyEvaluationResultSchema":
        return cls(
            policy_name=record.policy_name,
            rule_id=record.rule_id,
            decision=record.decision,
            severity=record.severity,
            reason=record.reason,
            evaluated_at=record.evaluated_at,
            metadata=dict(record.metadata),
            policy_version=record.policy_version,
        )


class PolicyViolationSchema(BaseModel):
    """Wire mirror of :class:`PolicyViolationRecord`."""

    model_config = ConfigDict(frozen=True)

    policy_name: str
    rule_id: str
    decision: str
    severity: int
    detail: str
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_record(
        cls, record: PolicyViolationRecord
    ) -> "PolicyViolationSchema":
        return cls(
            policy_name=record.policy_name,
            rule_id=record.rule_id,
            decision=record.decision,
            severity=record.severity,
            detail=record.detail,
            metadata=dict(record.metadata),
        )


class RuntimeRestrictionSchema(BaseModel):
    """Wire mirror of :class:`RuntimeRestrictionRecord`."""

    model_config = ConfigDict(frozen=True)

    kind: str
    target: str
    value: Any = None
    reason: str
    policy_name: str
    rule_id: str
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_record(
        cls, record: RuntimeRestrictionRecord
    ) -> "RuntimeRestrictionSchema":
        return cls(
            kind=record.kind,
            target=record.target,
            value=record.value,
            reason=record.reason,
            policy_name=record.policy_name,
            rule_id=record.rule_id,
            metadata=dict(record.metadata),
        )


class PolicyEvaluationTraceSchema(BaseModel):
    """Wire mirror of :class:`PolicyEvaluationTraceRecord`."""

    model_config = ConfigDict(frozen=True)

    policy_name: str
    status: str
    started_at: str
    ended_at: str
    latency_ms: float
    rule_count: int
    decision_counts: dict[str, int] = Field(default_factory=dict)
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_record(
        cls, record: PolicyEvaluationTraceRecord
    ) -> "PolicyEvaluationTraceSchema":
        return cls(
            policy_name=record.policy_name,
            status=record.status,
            started_at=record.started_at,
            ended_at=record.ended_at,
            latency_ms=record.latency_ms,
            rule_count=record.rule_count,
            decision_counts=dict(record.decision_counts),
            error=record.error,
            metadata=dict(record.metadata),
        )


# ─── Apex schemas ────────────────────────────────────────────────────────


class GovernanceDecisionResponse(BaseModel):
    """Wire mirror of :class:`GovernanceDecisionRecord` (one apex decision)."""

    model_config = ConfigDict(frozen=True)

    decision_id: str
    decision: str
    stage: str
    policy_chain_id: str
    reason: str
    decided_at: str
    correlation_id: str | None = None
    request_id: str | None = None
    tenant_id: str | None = None
    subject_kind: str
    governance_version: str
    violations: list[PolicyViolationSchema] = Field(default_factory=list)
    restrictions: list[RuntimeRestrictionSchema] = Field(default_factory=list)
    evaluated_rules: list[PolicyEvaluationResultSchema] = Field(
        default_factory=list
    )
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_record(
        cls, record: GovernanceDecisionRecord
    ) -> "GovernanceDecisionResponse":
        return cls(
            decision_id=record.decision_id,
            decision=record.decision,
            stage=record.stage,
            policy_chain_id=record.policy_chain_id,
            reason=record.reason,
            decided_at=record.decided_at,
            correlation_id=record.correlation_id,
            request_id=record.request_id,
            tenant_id=record.tenant_id,
            subject_kind=record.subject_kind,
            governance_version=record.governance_version,
            violations=[
                PolicyViolationSchema.from_record(v)
                for v in record.violations
            ],
            restrictions=[
                RuntimeRestrictionSchema.from_record(r)
                for r in record.restrictions
            ],
            evaluated_rules=[
                PolicyEvaluationResultSchema.from_record(e)
                for e in record.evaluated_rules
            ],
            metadata=dict(record.metadata),
        )


class GovernanceTraceResponse(BaseModel):
    """Wire mirror of :class:`GovernanceTraceRecord` (one apex trace)."""

    model_config = ConfigDict(frozen=True)

    decision_id: str
    request_id: str | None = None
    correlation_id: str | None = None
    stage: str
    action: str
    resource: str
    actor: str
    tenant_id: str | None = None
    subject_kind: str
    started_at: str
    ended_at: str
    latency_ms: float
    status: str
    final_decision: str
    policy_chain_id: str
    rule_count: int
    violation_count: int
    restriction_count: int
    enforcement_handler: str | None = None
    enforcement_status: str | None = None
    enforcement_latency_ms: float | None = None
    policy_traces: list[PolicyEvaluationTraceSchema] = Field(
        default_factory=list
    )
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_record(
        cls, record: GovernanceTraceRecord
    ) -> "GovernanceTraceResponse":
        return cls(
            decision_id=record.decision_id,
            request_id=record.request_id,
            correlation_id=record.correlation_id,
            stage=record.stage,
            action=record.action,
            resource=record.resource,
            actor=record.actor,
            tenant_id=record.tenant_id,
            subject_kind=record.subject_kind,
            started_at=record.started_at,
            ended_at=record.ended_at,
            latency_ms=record.latency_ms,
            status=record.status,
            final_decision=record.final_decision,
            policy_chain_id=record.policy_chain_id,
            rule_count=record.rule_count,
            violation_count=record.violation_count,
            restriction_count=record.restriction_count,
            enforcement_handler=record.enforcement_handler,
            enforcement_status=record.enforcement_status,
            enforcement_latency_ms=record.enforcement_latency_ms,
            policy_traces=[
                PolicyEvaluationTraceSchema.from_record(t)
                for t in record.policy_traces
            ],
            error=record.error,
            metadata=dict(record.metadata),
        )


class GovernanceDecisionsPage(BaseModel):
    """Paginated list of governance decisions."""

    model_config = ConfigDict(frozen=True)

    items: list[GovernanceDecisionResponse] = Field(default_factory=list)
    total: int = Field(
        ..., description="Total matching decisions before pagination."
    )
    offset: int = Field(..., description="Echo of the requested offset.")


__all__ = [
    "GovernanceDecisionResponse",
    "GovernanceDecisionsPage",
    "GovernanceTraceResponse",
    "PolicyEvaluationResultSchema",
    "PolicyEvaluationTraceSchema",
    "PolicyViolationSchema",
    "RuntimeRestrictionSchema",
]
