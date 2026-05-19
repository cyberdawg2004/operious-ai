"""Transport contracts for the v1 supervisor read endpoints.

Mirrors the four supervisor record types (Inspection, Finding,
Evaluation, Escalation) plus the embedded SupervisorDecisionRecord
and EvaluationEvidenceRecord, as frozen Pydantic schemas with
explicit ``from_record`` projections.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.supervisor.persistence import (
    EscalationDecisionRecord,
    EvaluationEvidenceRecord,
    InspectionRecord,
    QAEvaluationRecord,
    RuntimeFindingRecord,
    SupervisorDecisionRecord,
)


class EvaluationEvidenceSchema(BaseModel):
    model_config = ConfigDict(frozen=True)

    execution_id: str
    tool_invocation_ids: list[str] = Field(default_factory=list)
    governance_decision_ids: list[str] = Field(default_factory=list)
    state_transition_indices: list[int] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_record(
        cls, record: EvaluationEvidenceRecord
    ) -> "EvaluationEvidenceSchema":
        return cls(
            execution_id=record.execution_id,
            tool_invocation_ids=list(record.tool_invocation_ids),
            governance_decision_ids=list(record.governance_decision_ids),
            state_transition_indices=list(record.state_transition_indices),
            metadata=dict(record.metadata),
        )


class SupervisorDecisionSchema(BaseModel):
    model_config = ConfigDict(frozen=True)

    decision_id: str
    kind: str
    aggregate_score: float
    finding_ids: list[str] = Field(default_factory=list)
    escalation_ids: list[str] = Field(default_factory=list)
    reason: str
    decided_at: str
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_record(
        cls, record: SupervisorDecisionRecord
    ) -> "SupervisorDecisionSchema":
        return cls(
            decision_id=record.decision_id,
            kind=record.kind,
            aggregate_score=record.aggregate_score,
            finding_ids=list(record.finding_ids),
            escalation_ids=list(record.escalation_ids),
            reason=record.reason,
            decided_at=record.decided_at,
            metadata=dict(record.metadata),
        )


class RuntimeFindingSchema(BaseModel):
    model_config = ConfigDict(frozen=True)

    finding_id: str
    evaluator_name: str
    category: str
    severity: str
    code: str
    message: str
    evidence: EvaluationEvidenceSchema
    detected_at: str
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_record(
        cls, record: RuntimeFindingRecord
    ) -> "RuntimeFindingSchema":
        return cls(
            finding_id=record.finding_id,
            evaluator_name=record.evaluator_name,
            category=record.category,
            severity=record.severity,
            code=record.code,
            message=record.message,
            evidence=EvaluationEvidenceSchema.from_record(record.evidence),
            detected_at=record.detected_at,
            metadata=dict(record.metadata),
        )


class QAEvaluationSchema(BaseModel):
    model_config = ConfigDict(frozen=True)

    inspection_id: str
    evaluator_name: str
    status: str
    score: float
    finding_ids: list[str] = Field(default_factory=list)
    started_at: str
    ended_at: str
    latency_ms: float
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_record(
        cls, record: QAEvaluationRecord
    ) -> "QAEvaluationSchema":
        return cls(
            inspection_id=record.inspection_id,
            evaluator_name=record.evaluator_name,
            status=record.status,
            score=record.score,
            finding_ids=list(record.finding_ids),
            started_at=record.started_at,
            ended_at=record.ended_at,
            latency_ms=record.latency_ms,
            error=record.error,
            metadata=dict(record.metadata),
        )


class EscalationDecisionSchema(BaseModel):
    model_config = ConfigDict(frozen=True)

    escalation_id: str
    inspection_id: str
    decision_id: str
    level: str
    reason: str
    triggering_finding_ids: list[str] = Field(default_factory=list)
    decided_at: str
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_record(
        cls, record: EscalationDecisionRecord
    ) -> "EscalationDecisionSchema":
        return cls(
            escalation_id=record.escalation_id,
            inspection_id=record.inspection_id,
            decision_id=record.decision_id,
            level=record.level,
            reason=record.reason,
            triggering_finding_ids=list(record.triggering_finding_ids),
            decided_at=record.decided_at,
            metadata=dict(record.metadata),
        )


class InspectionResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    inspection_id: str
    execution_id: str
    runtime_instance_id: str
    correlation_id: str | None = None
    request_id: str | None = None
    tenant_id: str | None = None
    inspection_mode: str
    decision: SupervisorDecisionSchema
    evaluator_names: list[str] = Field(default_factory=list)
    started_at: str
    ended_at: str
    latency_ms: float
    error: str | None = None
    tenant_authority_source: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_record(cls, record: InspectionRecord) -> "InspectionResponse":
        return cls(
            inspection_id=record.inspection_id,
            execution_id=record.execution_id,
            runtime_instance_id=record.runtime_instance_id,
            correlation_id=record.correlation_id,
            request_id=record.request_id,
            tenant_id=record.tenant_id,
            inspection_mode=record.inspection_mode,
            decision=SupervisorDecisionSchema.from_record(record.decision),
            evaluator_names=list(record.evaluator_names),
            started_at=record.started_at,
            ended_at=record.ended_at,
            latency_ms=record.latency_ms,
            error=record.error,
            tenant_authority_source=record.tenant_authority_source,
            metadata=dict(record.metadata),
        )


class InspectionsPage(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[InspectionResponse] = Field(default_factory=list)
    total: int
    offset: int


class InspectionFindingsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    inspection_id: str
    items: list[RuntimeFindingSchema] = Field(default_factory=list)


class InspectionEvaluationsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    inspection_id: str
    items: list[QAEvaluationSchema] = Field(default_factory=list)


class InspectionEscalationsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    inspection_id: str
    items: list[EscalationDecisionSchema] = Field(default_factory=list)


__all__ = [
    "EscalationDecisionSchema",
    "EvaluationEvidenceSchema",
    "InspectionEscalationsResponse",
    "InspectionEvaluationsResponse",
    "InspectionFindingsResponse",
    "InspectionResponse",
    "InspectionsPage",
    "QAEvaluationSchema",
    "RuntimeFindingSchema",
    "SupervisorDecisionSchema",
]
