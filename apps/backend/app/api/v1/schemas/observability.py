"""Transport contracts for operational observability endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.observability.persistence import (
    DeadLetterExecutionPage,
    DeadLetterExecutionRecord,
    InboundNormalizationDeadLetterPage,
    InboundNormalizationDeadLetterRecord,
    OperationalAlertPage,
    OperationalAlertRecord,
    OperationalMetricsSnapshotRecord,
    OperationalSLODefinitionPage,
    OperationalSLODefinitionRecord,
    OperationalTraceSpanPage,
    OperationalTraceSpanRecord,
    QAScoreBucketRecord,
    StuckExecutionAlertPage,
    StuckExecutionAlertRecord,
)


class QAScoreBucketResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    lower_bound: float
    upper_bound: float
    count: int

    @classmethod
    def from_record(cls, record: QAScoreBucketRecord) -> "QAScoreBucketResponse":
        return cls(
            lower_bound=record.lower_bound,
            upper_bound=record.upper_bound,
            count=record.count,
        )


class OperationalMetricsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    tenant_id: str
    window_start: datetime
    window_end: datetime
    ticket_throughput: int
    governance_decision_count: int
    governance_deny_count: int
    governance_deny_rate: float
    execution_count: int
    completed_execution_count: int
    execution_latency_ms_avg: float | None
    execution_latency_ms_p50: float | None
    execution_latency_ms_p95: float | None
    qa_score_count: int
    qa_score_average: float | None
    qa_score_distribution: list[QAScoreBucketResponse]
    escalation_count: int
    escalation_rate: float
    dlq_count: int

    @classmethod
    def from_record(
        cls,
        record: OperationalMetricsSnapshotRecord,
    ) -> "OperationalMetricsResponse":
        return cls(
            tenant_id=record.tenant_id,
            window_start=record.window_start,
            window_end=record.window_end,
            ticket_throughput=record.ticket_throughput,
            governance_decision_count=record.governance_decision_count,
            governance_deny_count=record.governance_deny_count,
            governance_deny_rate=record.governance_deny_rate,
            execution_count=record.execution_count,
            completed_execution_count=record.completed_execution_count,
            execution_latency_ms_avg=record.execution_latency_ms_avg,
            execution_latency_ms_p50=record.execution_latency_ms_p50,
            execution_latency_ms_p95=record.execution_latency_ms_p95,
            qa_score_count=record.qa_score_count,
            qa_score_average=record.qa_score_average,
            qa_score_distribution=[
                QAScoreBucketResponse.from_record(bucket)
                for bucket in record.qa_score_distribution
            ],
            escalation_count=record.escalation_count,
            escalation_rate=record.escalation_rate,
            dlq_count=record.dlq_count,
        )


class DeadLetterExecutionResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    execution_id: str
    tenant_id: str
    kind: str
    dispatch_id: str
    session_id: str
    state: str
    attempt_count: int
    requested_at: datetime
    failed_at: datetime | None
    worker_id: str | None
    error: str | None
    metadata: dict[str, Any]

    @classmethod
    def from_record(
        cls,
        record: DeadLetterExecutionRecord,
    ) -> "DeadLetterExecutionResponse":
        return cls(
            execution_id=record.execution_id,
            tenant_id=record.tenant_id,
            kind=record.kind,
            dispatch_id=record.dispatch_id,
            session_id=record.session_id,
            state=record.state,
            attempt_count=record.attempt_count,
            requested_at=record.requested_at,
            failed_at=record.failed_at,
            worker_id=record.worker_id,
            error=record.error,
            metadata=dict(record.metadata),
        )


class DeadLetterExecutionPageResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[DeadLetterExecutionResponse]
    total: int
    offset: int

    @classmethod
    def from_page(
        cls,
        page: DeadLetterExecutionPage,
    ) -> "DeadLetterExecutionPageResponse":
        return cls(
            items=[
                DeadLetterExecutionResponse.from_record(record)
                for record in page.items
            ],
            total=page.total,
            offset=page.offset,
        )


class StuckExecutionAlertResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    alert_id: str
    tenant_id: str
    execution_id: str
    reason: str
    claimed_at: datetime | None
    worker_id: str | None
    metadata: dict[str, Any]

    @classmethod
    def from_record(
        cls,
        record: StuckExecutionAlertRecord,
    ) -> "StuckExecutionAlertResponse":
        return cls(
            alert_id=record.alert_id,
            tenant_id=record.tenant_id,
            execution_id=record.execution_id,
            reason=record.reason,
            claimed_at=record.claimed_at,
            worker_id=record.worker_id,
            metadata=dict(record.metadata),
        )


class StuckExecutionAlertPageResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[StuckExecutionAlertResponse]
    total: int
    offset: int

    @classmethod
    def from_page(
        cls,
        page: StuckExecutionAlertPage,
    ) -> "StuckExecutionAlertPageResponse":
        return cls(
            items=[
                StuckExecutionAlertResponse.from_record(record)
                for record in page.items
            ],
            total=page.total,
            offset=page.offset,
        )


class InboundNormalizationDeadLetterResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    dead_letter_id: str
    tenant_id: str
    ingress_id: str
    normalization_status: str
    error: str | None
    received_at: datetime
    metadata: dict[str, Any]

    @classmethod
    def from_record(
        cls,
        record: InboundNormalizationDeadLetterRecord,
    ) -> "InboundNormalizationDeadLetterResponse":
        return cls(
            dead_letter_id=record.dead_letter_id,
            tenant_id=record.tenant_id,
            ingress_id=record.ingress_id,
            normalization_status=record.normalization_status,
            error=record.error,
            received_at=record.received_at,
            metadata=dict(record.metadata),
        )


class InboundNormalizationDeadLetterPageResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[InboundNormalizationDeadLetterResponse]
    total: int
    offset: int

    @classmethod
    def from_page(
        cls,
        page: InboundNormalizationDeadLetterPage,
    ) -> "InboundNormalizationDeadLetterPageResponse":
        return cls(
            items=[
                InboundNormalizationDeadLetterResponse.from_record(record)
                for record in page.items
            ],
            total=page.total,
            offset=page.offset,
        )


class OperationalSLODefinitionRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    metric_name: str = Field(min_length=1)
    threshold_operator: str = Field(min_length=1)
    threshold_value: float
    window_minutes: int = Field(ge=1)
    severity: str = Field(default="warning", min_length=1)
    enabled: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class OperationalSLODefinitionResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    slo_id: str
    tenant_id: str
    metric_name: str
    threshold_operator: str
    threshold_value: float
    window_minutes: int
    severity: str
    enabled: bool
    created_at: datetime
    updated_at: datetime
    metadata: dict[str, Any]

    @classmethod
    def from_record(
        cls,
        record: OperationalSLODefinitionRecord,
    ) -> "OperationalSLODefinitionResponse":
        return cls(
            slo_id=str(record.slo_id),
            tenant_id=record.tenant_id,
            metric_name=record.metric_name.value,
            threshold_operator=record.threshold_operator.value,
            threshold_value=record.threshold_value,
            window_minutes=record.window_minutes,
            severity=record.severity.value,
            enabled=record.enabled,
            created_at=record.created_at,
            updated_at=record.updated_at,
            metadata=dict(record.metadata),
        )


class OperationalSLODefinitionPageResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[OperationalSLODefinitionResponse]
    total: int
    offset: int

    @classmethod
    def from_page(
        cls,
        page: OperationalSLODefinitionPage,
    ) -> "OperationalSLODefinitionPageResponse":
        return cls(
            items=[
                OperationalSLODefinitionResponse.from_record(record)
                for record in page.items
            ],
            total=page.total,
            offset=page.offset,
        )


class OperationalAlertResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    alert_id: str
    tenant_id: str
    slo_id: str
    metric_name: str
    severity: str
    threshold_operator: str
    threshold_value: float
    observed_value: float
    window_start: datetime
    window_end: datetime
    triggered: bool
    metadata: dict[str, Any]

    @classmethod
    def from_record(cls, record: OperationalAlertRecord) -> "OperationalAlertResponse":
        return cls(
            alert_id=str(record.alert_id),
            tenant_id=record.tenant_id,
            slo_id=str(record.slo_id),
            metric_name=record.metric_name.value,
            severity=record.severity.value,
            threshold_operator=record.threshold_operator.value,
            threshold_value=record.threshold_value,
            observed_value=record.observed_value,
            window_start=record.window_start,
            window_end=record.window_end,
            triggered=record.triggered,
            metadata=dict(record.metadata),
        )


class OperationalAlertPageResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[OperationalAlertResponse]
    total: int
    offset: int

    @classmethod
    def from_page(
        cls,
        page: OperationalAlertPage,
    ) -> "OperationalAlertPageResponse":
        return cls(
            items=[OperationalAlertResponse.from_record(record) for record in page.items],
            total=page.total,
            offset=page.offset,
        )


class OperationalTraceSpanRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    trace_id: str = Field(min_length=1)
    parent_span_id: str | None = None
    span_name: str = Field(min_length=1)
    substrate: str = Field(min_length=1)
    operation: str = Field(min_length=1)
    started_at: datetime
    ended_at: datetime
    status: str = Field(default="ok", min_length=1)
    error: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class OperationalTraceSpanResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    span_id: str
    tenant_id: str
    trace_id: str
    parent_span_id: str | None
    span_name: str
    substrate: str
    operation: str
    started_at: datetime
    ended_at: datetime
    latency_ms: float
    status: str
    error: str | None
    attributes: dict[str, Any]
    created_at: datetime | None

    @classmethod
    def from_record(
        cls,
        record: OperationalTraceSpanRecord,
    ) -> "OperationalTraceSpanResponse":
        return cls(
            span_id=str(record.span_id),
            tenant_id=record.tenant_id,
            trace_id=record.trace_id,
            parent_span_id=(
                str(record.parent_span_id)
                if record.parent_span_id is not None
                else None
            ),
            span_name=record.span_name,
            substrate=record.substrate,
            operation=record.operation,
            started_at=record.started_at,
            ended_at=record.ended_at,
            latency_ms=record.latency_ms,
            status=record.status.value,
            error=record.error,
            attributes=dict(record.attributes),
            created_at=record.created_at,
        )


class OperationalTraceSpanPageResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[OperationalTraceSpanResponse]
    total: int
    offset: int

    @classmethod
    def from_page(
        cls,
        page: OperationalTraceSpanPage,
    ) -> "OperationalTraceSpanPageResponse":
        return cls(
            items=[
                OperationalTraceSpanResponse.from_record(record)
                for record in page.items
            ],
            total=page.total,
            offset=page.offset,
        )


__all__ = [
    "DeadLetterExecutionPageResponse",
    "DeadLetterExecutionResponse",
    "InboundNormalizationDeadLetterPageResponse",
    "InboundNormalizationDeadLetterResponse",
    "OperationalAlertPageResponse",
    "OperationalAlertResponse",
    "OperationalMetricsResponse",
    "OperationalSLODefinitionPageResponse",
    "OperationalSLODefinitionRequest",
    "OperationalSLODefinitionResponse",
    "OperationalTraceSpanPageResponse",
    "OperationalTraceSpanRequest",
    "OperationalTraceSpanResponse",
    "QAScoreBucketResponse",
    "StuckExecutionAlertPageResponse",
    "StuckExecutionAlertResponse",
]
