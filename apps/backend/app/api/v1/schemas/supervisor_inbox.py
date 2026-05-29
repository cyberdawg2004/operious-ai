"""Transport contracts for the supervisor inbox."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.api.v1.schemas.supervisor import (
    EscalationDecisionSchema,
    InspectionResponse,
    QAEvaluationSchema,
    RuntimeFindingSchema,
    SupervisorDecisionSchema,
)
from app.api.v1.schemas.trainer import TrainingRecommendationResponse
from app.qa.persistence import QAScoreRecord
from app.services.supervisor_inbox_service import (
    SupervisorInboxItem,
    SupervisorInboxPage,
    SupervisorInspectionDetail,
)


def _empty_inbox_items() -> list[SupervisorInspectionInboxItemResponse]:
    return []


def _empty_findings() -> list[RuntimeFindingSchema]:
    return []


def _empty_evaluations() -> list[QAEvaluationSchema]:
    return []


def _empty_escalations() -> list[EscalationDecisionSchema]:
    return []


def _empty_training_recommendations() -> list[TrainingRecommendationResponse]:
    return []


class QAScoreResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    score_id: str
    inspection_id: str
    execution_id: str
    tenant_id: str
    tenant_authority_source: str | None = None
    diagnostic_accuracy: float
    policy_compliance: float
    timeline_integrity: float
    resolution_quality: float
    overall_score: float
    supervisor_decision_kind: str
    finding_count: int
    evaluation_count: int
    escalation_count: int
    scored_at: str
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_record(cls, record: QAScoreRecord) -> "QAScoreResponse":
        return cls(
            score_id=record.score_id,
            inspection_id=record.inspection_id,
            execution_id=record.execution_id,
            tenant_id=record.tenant_id,
            tenant_authority_source=record.tenant_authority_source,
            diagnostic_accuracy=record.diagnostic_accuracy,
            policy_compliance=record.policy_compliance,
            timeline_integrity=record.timeline_integrity,
            resolution_quality=record.resolution_quality,
            overall_score=record.overall_score,
            supervisor_decision_kind=record.supervisor_decision_kind,
            finding_count=record.finding_count,
            evaluation_count=record.evaluation_count,
            escalation_count=record.escalation_count,
            scored_at=record.scored_at,
            metadata=dict(record.metadata),
        )


class SupervisorInspectionInboxItemResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    inspection_id: str
    execution_id: str
    tenant_id: str | None
    session_id: str | None
    category: str
    decision_kind: str
    aggregate_score: float
    started_at: str
    ended_at: str
    escalation_count: int
    is_risky: bool
    qa_score: QAScoreResponse | None = None
    inspection: InspectionResponse

    @classmethod
    def from_item(
        cls,
        item: SupervisorInboxItem,
    ) -> "SupervisorInspectionInboxItemResponse":
        return cls(
            inspection_id=item.inspection.inspection_id,
            execution_id=item.inspection.execution_id,
            tenant_id=item.inspection.tenant_id,
            session_id=item.session_id,
            category=item.category,
            decision_kind=item.inspection.decision.kind,
            aggregate_score=item.inspection.decision.aggregate_score,
            started_at=item.inspection.started_at,
            ended_at=item.inspection.ended_at,
            escalation_count=item.escalation_count,
            is_risky=item.is_risky,
            qa_score=(
                QAScoreResponse.from_record(item.qa_score)
                if item.qa_score is not None
                else None
            ),
            inspection=InspectionResponse.from_record(item.inspection),
        )


class SupervisorInspectionListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[SupervisorInspectionInboxItemResponse] = Field(
        default_factory=_empty_inbox_items
    )
    total: int
    offset: int
    limit: int

    @classmethod
    def from_page(
        cls,
        page: SupervisorInboxPage,
    ) -> "SupervisorInspectionListResponse":
        return cls(
            items=[
                SupervisorInspectionInboxItemResponse.from_item(item)
                for item in page.items
            ],
            total=page.total,
            offset=page.offset,
            limit=page.limit,
        )


class SupervisorInspectionDetailResponse(BaseModel):
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
    inspection: InspectionResponse
    qa_score: QAScoreResponse | None = None
    findings: list[RuntimeFindingSchema] = Field(default_factory=_empty_findings)
    evaluations: list[QAEvaluationSchema] = Field(
        default_factory=_empty_evaluations
    )
    escalations: list[EscalationDecisionSchema] = Field(
        default_factory=_empty_escalations
    )
    training_recommendations: list[TrainingRecommendationResponse] = Field(
        default_factory=_empty_training_recommendations
    )
    category: str
    session_id: str | None
    is_risky: bool

    @classmethod
    def from_detail(
        cls,
        detail: SupervisorInspectionDetail,
    ) -> "SupervisorInspectionDetailResponse":
        inspection = InspectionResponse.from_record(detail.inspection)
        return cls(
            inspection_id=inspection.inspection_id,
            execution_id=inspection.execution_id,
            runtime_instance_id=inspection.runtime_instance_id,
            correlation_id=inspection.correlation_id,
            request_id=inspection.request_id,
            tenant_id=inspection.tenant_id,
            inspection_mode=inspection.inspection_mode,
            decision=inspection.decision,
            evaluator_names=list(inspection.evaluator_names),
            started_at=inspection.started_at,
            ended_at=inspection.ended_at,
            latency_ms=inspection.latency_ms,
            error=inspection.error,
            tenant_authority_source=inspection.tenant_authority_source,
            metadata=dict(inspection.metadata),
            inspection=inspection,
            qa_score=(
                QAScoreResponse.from_record(detail.qa_score)
                if detail.qa_score is not None
                else None
            ),
            findings=[
                RuntimeFindingSchema.from_record(record)
                for record in detail.findings
            ],
            evaluations=[
                QAEvaluationSchema.from_record(record)
                for record in detail.evaluations
            ],
            escalations=[
                EscalationDecisionSchema.from_record(record)
                for record in detail.escalations
            ],
            training_recommendations=[
                TrainingRecommendationResponse.from_record(record)
                for record in detail.training_recommendations
            ],
            category=detail.category,
            session_id=detail.session_id,
            is_risky=detail.is_risky,
        )


__all__ = [
    "QAScoreResponse",
    "SupervisorInspectionDetailResponse",
    "SupervisorInspectionInboxItemResponse",
    "SupervisorInspectionListResponse",
]
