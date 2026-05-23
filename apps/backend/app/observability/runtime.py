"""Operational observability runtime."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from app.observability.enums import (
    AlertSeverity,
    AlertThresholdOperator,
    OperationalMetricName,
    OperationalTraceStatus,
)
from app.observability.identity import (
    OperationalSLODefinitionId,
    OperationalTraceSpanId,
    derive_alert_id,
    derive_slo_definition_id,
    derive_trace_span_id,
)
from app.observability.persistence.calculations import metric_value
from app.observability.persistence.models import (
    DeadLetterExecutionPage,
    DeadLetterExecutionQuery,
    InboundNormalizationDeadLetterPage,
    InboundNormalizationDeadLetterQuery,
    OperationalAlertPage,
    OperationalMetricsQuery,
    OperationalSLODefinitionPage,
    OperationalSLODefinitionQuery,
    OperationalTraceSpanPage,
    OperationalTraceSpanQuery,
    StuckExecutionAlertPage,
    StuckExecutionAlertQuery,
)
from app.observability.persistence.records import (
    OperationalAlertRecord,
    OperationalMetricsSnapshotRecord,
    OperationalSLODefinitionRecord,
    OperationalTraceSpanRecord,
)
from app.observability.persistence.repository import (
    OperationalObservabilityPersistence,
)


class OperationalObservabilityRuntime:
    """Read/config authority for tenant operational observability."""

    def __init__(
        self,
        *,
        persistence: OperationalObservabilityPersistence,
    ) -> None:
        self._persistence = persistence

    async def read_metrics(
        self,
        *,
        query: OperationalMetricsQuery,
        expected_tenant_id: str,
    ) -> OperationalMetricsSnapshotRecord:
        return await self._persistence.read_metrics(
            query,
            expected_tenant_id=expected_tenant_id,
        )

    async def list_dead_letters(
        self,
        *,
        query: DeadLetterExecutionQuery,
        expected_tenant_id: str,
    ) -> DeadLetterExecutionPage:
        return await self._persistence.list_dead_letter_executions(
            query,
            expected_tenant_id=expected_tenant_id,
        )

    async def list_stuck_execution_alerts(
        self,
        *,
        query: StuckExecutionAlertQuery,
        expected_tenant_id: str,
    ) -> StuckExecutionAlertPage:
        return await self._persistence.list_stuck_execution_alerts(
            query,
            expected_tenant_id=expected_tenant_id,
        )

    async def list_inbound_normalization_dead_letters(
        self,
        *,
        query: InboundNormalizationDeadLetterQuery,
        expected_tenant_id: str,
    ) -> InboundNormalizationDeadLetterPage:
        return await self._persistence.list_inbound_normalization_dead_letters(
            query,
            expected_tenant_id=expected_tenant_id,
        )

    async def define_slo(
        self,
        *,
        tenant_id: str,
        metric_name: OperationalMetricName,
        threshold_operator: AlertThresholdOperator,
        threshold_value: float,
        window_minutes: int,
        severity: AlertSeverity,
        enabled: bool = True,
        metadata: Mapping[str, Any] | None = None,
        now: datetime | None = None,
    ) -> OperationalSLODefinitionRecord:
        timestamp = now or datetime.now(tz=timezone.utc)
        slo_id = derive_slo_definition_id(
            tenant_id=tenant_id,
            metric_name=metric_name,
            window_minutes=window_minutes,
            severity=severity,
        )
        record = OperationalSLODefinitionRecord(
            slo_id=slo_id,
            tenant_id=tenant_id,
            metric_name=metric_name,
            threshold_operator=threshold_operator,
            threshold_value=threshold_value,
            window_minutes=window_minutes,
            severity=severity,
            enabled=enabled,
            created_at=timestamp,
            updated_at=timestamp,
            metadata=dict(metadata or {}),
        )
        return await self._persistence.save_slo_definition(
            record,
            expected_tenant_id=tenant_id,
        )

    async def get_slo_definition(
        self,
        *,
        slo_id: OperationalSLODefinitionId,
        expected_tenant_id: str,
    ) -> OperationalSLODefinitionRecord | None:
        return await self._persistence.get_slo_definition(
            slo_id,
            expected_tenant_id=expected_tenant_id,
        )

    async def list_slo_definitions(
        self,
        *,
        query: OperationalSLODefinitionQuery,
        expected_tenant_id: str,
    ) -> OperationalSLODefinitionPage:
        return await self._persistence.list_slo_definitions(
            query,
            expected_tenant_id=expected_tenant_id,
        )

    async def record_trace_span(
        self,
        *,
        tenant_id: str,
        trace_id: str,
        span_name: str,
        substrate: str,
        operation: str,
        started_at: datetime,
        ended_at: datetime,
        status: OperationalTraceStatus,
        parent_span_id: OperationalTraceSpanId | None = None,
        error: str | None = None,
        attributes: Mapping[str, Any] | None = None,
        created_at: datetime | None = None,
    ) -> OperationalTraceSpanRecord:
        if ended_at < started_at:
            raise ValueError("ended_at must be greater than or equal to started_at")
        span_id = derive_trace_span_id(
            tenant_id=tenant_id,
            trace_id=trace_id,
            parent_span_id=parent_span_id,
            span_name=span_name,
            operation=operation,
            started_at=started_at,
        )
        latency_ms = (ended_at - started_at).total_seconds() * 1000.0
        record = OperationalTraceSpanRecord(
            span_id=span_id,
            tenant_id=tenant_id,
            trace_id=trace_id,
            parent_span_id=parent_span_id,
            span_name=span_name,
            substrate=substrate,
            operation=operation,
            started_at=started_at,
            ended_at=ended_at,
            latency_ms=round(max(latency_ms, 0.0), 6),
            status=status,
            error=error,
            attributes=dict(attributes or {}),
            created_at=created_at or datetime.now(tz=timezone.utc),
        )
        return await self._persistence.save_trace_span(
            record,
            expected_tenant_id=tenant_id,
        )

    async def get_trace_span(
        self,
        *,
        span_id: OperationalTraceSpanId,
        expected_tenant_id: str,
    ) -> OperationalTraceSpanRecord | None:
        return await self._persistence.get_trace_span(
            span_id,
            expected_tenant_id=expected_tenant_id,
        )

    async def list_trace_spans(
        self,
        *,
        query: OperationalTraceSpanQuery,
        expected_tenant_id: str,
    ) -> OperationalTraceSpanPage:
        return await self._persistence.list_trace_spans(
            query,
            expected_tenant_id=expected_tenant_id,
        )

    async def evaluate_alerts(
        self,
        *,
        query: OperationalMetricsQuery,
        expected_tenant_id: str,
    ) -> OperationalAlertPage:
        snapshot = await self.read_metrics(
            query=query,
            expected_tenant_id=expected_tenant_id,
        )
        definitions = await self.list_slo_definitions(
            query=OperationalSLODefinitionQuery(enabled=True),
            expected_tenant_id=expected_tenant_id,
        )
        alerts: list[OperationalAlertRecord] = []
        for definition in definitions.items:
            observed = metric_value(snapshot, definition.metric_name.value)
            triggered = _compare(
                observed=observed,
                operator=definition.threshold_operator,
                threshold=definition.threshold_value,
            )
            alerts.append(
                OperationalAlertRecord(
                    alert_id=derive_alert_id(
                        tenant_id=expected_tenant_id,
                        slo_id=definition.slo_id,
                        window_start=query.window_start,
                        window_end=query.window_end,
                    ),
                    tenant_id=expected_tenant_id,
                    slo_id=definition.slo_id,
                    metric_name=definition.metric_name,
                    severity=definition.severity,
                    threshold_operator=definition.threshold_operator,
                    threshold_value=definition.threshold_value,
                    observed_value=observed,
                    window_start=query.window_start,
                    window_end=query.window_end,
                    triggered=triggered,
                    metadata=dict(definition.metadata),
                )
            )
        return OperationalAlertPage(
            items=tuple(alerts),
            total=len(alerts),
            offset=0,
        )


def _compare(
    *,
    observed: float,
    operator: AlertThresholdOperator,
    threshold: float,
) -> bool:
    if operator is AlertThresholdOperator.GREATER_THAN:
        return observed > threshold
    if operator is AlertThresholdOperator.GREATER_THAN_OR_EQUAL:
        return observed >= threshold
    if operator is AlertThresholdOperator.LESS_THAN:
        return observed < threshold
    if operator is AlertThresholdOperator.LESS_THAN_OR_EQUAL:
        return observed <= threshold
    raise ValueError(f"unsupported alert threshold operator: {operator}")


__all__ = ["OperationalObservabilityRuntime"]
