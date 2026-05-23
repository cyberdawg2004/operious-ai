"""Frozen operational observability persistence records."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from app.observability.enums import (
    AlertSeverity,
    AlertThresholdOperator,
    OperationalMetricName,
    OperationalTraceStatus,
)
from app.observability.identity import (
    OperationalAlertId,
    OperationalSLODefinitionId,
    OperationalTraceSpanId,
)


@dataclass(frozen=True, slots=True)
class QAScoreBucketRecord:
    lower_bound: float
    upper_bound: float
    count: int


@dataclass(frozen=True, slots=True)
class OperationalMetricsSnapshotRecord:
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
    qa_score_distribution: tuple[QAScoreBucketRecord, ...]
    escalation_count: int
    escalation_rate: float
    dlq_count: int


@dataclass(frozen=True, slots=True)
class DeadLetterExecutionRecord:
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
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class OperationalSLODefinitionRecord:
    slo_id: OperationalSLODefinitionId
    tenant_id: str
    metric_name: OperationalMetricName
    threshold_operator: AlertThresholdOperator
    threshold_value: float
    window_minutes: int
    severity: AlertSeverity
    enabled: bool
    created_at: datetime
    updated_at: datetime
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class OperationalTraceSpanRecord:
    span_id: OperationalTraceSpanId
    tenant_id: str
    trace_id: str
    parent_span_id: OperationalTraceSpanId | None
    span_name: str
    substrate: str
    operation: str
    started_at: datetime
    ended_at: datetime
    latency_ms: float
    status: OperationalTraceStatus
    error: str | None
    attributes: Mapping[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class OperationalAlertRecord:
    alert_id: OperationalAlertId
    tenant_id: str
    slo_id: OperationalSLODefinitionId
    metric_name: OperationalMetricName
    severity: AlertSeverity
    threshold_operator: AlertThresholdOperator
    threshold_value: float
    observed_value: float
    window_start: datetime
    window_end: datetime
    triggered: bool
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class StuckExecutionAlertRecord:
    alert_id: str
    tenant_id: str
    execution_id: str
    reason: str
    claimed_at: datetime | None
    worker_id: str | None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class InboundNormalizationDeadLetterRecord:
    dead_letter_id: str
    tenant_id: str
    ingress_id: str
    normalization_status: str
    error: str | None
    received_at: datetime
    metadata: Mapping[str, Any] = field(default_factory=dict)


__all__ = [
    "DeadLetterExecutionRecord",
    "InboundNormalizationDeadLetterRecord",
    "OperationalAlertRecord",
    "OperationalMetricsSnapshotRecord",
    "OperationalSLODefinitionRecord",
    "OperationalTraceSpanRecord",
    "QAScoreBucketRecord",
    "StuckExecutionAlertRecord",
]
