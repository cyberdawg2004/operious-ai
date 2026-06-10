"""Operational observability application service boundary."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from sqlalchemy.ext.asyncio import AsyncSession

from app.observability.enums import (
    AlertSeverity,
    AlertThresholdOperator,
    OperationalMetricName,
    OperationalTraceStatus,
)
from app.observability.identity import (
    OperationalTraceSpanId,
    as_operational_slo_id,
)
from app.observability.persistence import (
    DeadLetterExecutionPage,
    DeadLetterExecutionQuery,
    InboundNormalizationDeadLetterPage,
    InboundNormalizationDeadLetterQuery,
    InboundMessageTimelineLookup,
    InboundMessageTimelineRecord,
    OperationalAlertPage,
    OperationalMetricsQuery,
    OperationalMetricsSnapshotRecord,
    OperationalSLODefinitionPage,
    OperationalSLODefinitionQuery,
    OperationalSLODefinitionRecord,
    OperationalTraceSpanPage,
    OperationalTraceSpanQuery,
    OperationalTraceSpanRecord,
    StuckExecutionAlertPage,
    StuckExecutionAlertQuery,
)
from app.observability.runtime import OperationalObservabilityRuntime


class OperationalObservabilityService:
    """Command Center service for metrics, SLOs, traces, and DLQ reads."""

    def __init__(
        self,
        *,
        runtime: OperationalObservabilityRuntime,
        session: AsyncSession,
    ) -> None:
        self._runtime = runtime
        self._session = session

    async def read_metrics(
        self,
        *,
        tenant_id: str,
        window_start: datetime,
        window_end: datetime,
    ) -> OperationalMetricsSnapshotRecord:
        return await self._runtime.read_metrics(
            query=OperationalMetricsQuery(
                window_start=window_start,
                window_end=window_end,
            ),
            expected_tenant_id=tenant_id,
        )

    async def list_dead_letters(
        self,
        *,
        tenant_id: str,
        execution_id: str | None,
        limit: int,
        offset: int,
    ) -> DeadLetterExecutionPage:
        return await self._runtime.list_dead_letters(
            query=DeadLetterExecutionQuery(
                execution_id=execution_id,
                limit=limit,
                offset=offset,
            ),
            expected_tenant_id=tenant_id,
        )

    async def list_stuck_execution_alerts(
        self,
        *,
        tenant_id: str,
        claimed_before_or_at: datetime,
        limit: int,
        offset: int,
    ) -> StuckExecutionAlertPage:
        return await self._runtime.list_stuck_execution_alerts(
            query=StuckExecutionAlertQuery(
                claimed_before_or_at=claimed_before_or_at,
                limit=limit,
                offset=offset,
            ),
            expected_tenant_id=tenant_id,
        )

    async def list_inbound_normalization_dead_letters(
        self,
        *,
        tenant_id: str,
        normalization_status: str | None,
        limit: int,
        offset: int,
    ) -> InboundNormalizationDeadLetterPage:
        return await self._runtime.list_inbound_normalization_dead_letters(
            query=InboundNormalizationDeadLetterQuery(
                normalization_status=normalization_status,
                limit=limit,
                offset=offset,
            ),
            expected_tenant_id=tenant_id,
        )

    async def get_inbound_message_timeline(
        self,
        *,
        tenant_id: str,
        lookup: InboundMessageTimelineLookup | None = None,
        ingress_id: str | None = None,
        external_conversation_id: str | None = None,
        session_id: str | None = None,
        execution_id: str | None = None,
        draft_id: str | None = None,
        outbound_send_outbox_id: str | None = None,
        stall_threshold_seconds: int,
        now: datetime | None = None,
    ) -> InboundMessageTimelineRecord:
        resolved_lookup = lookup or InboundMessageTimelineLookup(
            ingress_id=ingress_id,
            external_conversation_id=external_conversation_id,
            session_id=session_id,
            execution_id=execution_id,
            draft_id=draft_id,
            outbound_send_outbox_id=outbound_send_outbox_id,
        )
        return await self._runtime.get_inbound_message_timeline(
            lookup=resolved_lookup,
            expected_tenant_id=tenant_id,
            stall_threshold_seconds=stall_threshold_seconds,
            now=now,
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
        enabled: bool,
        metadata: Mapping[str, Any],
    ) -> OperationalSLODefinitionRecord:
        try:
            record = await self._runtime.define_slo(
                tenant_id=tenant_id,
                metric_name=metric_name,
                threshold_operator=threshold_operator,
                threshold_value=threshold_value,
                window_minutes=window_minutes,
                severity=severity,
                enabled=enabled,
                metadata=metadata,
            )
            await self._session.commit()
            return record
        except Exception:
            await self._session.rollback()
            raise

    async def get_slo_definition(
        self,
        *,
        tenant_id: str,
        slo_id: str,
    ) -> OperationalSLODefinitionRecord | None:
        return await self._runtime.get_slo_definition(
            slo_id=as_operational_slo_id(slo_id),
            expected_tenant_id=tenant_id,
        )

    async def list_slo_definitions(
        self,
        *,
        tenant_id: str,
        metric_name: OperationalMetricName | None,
        enabled: bool | None,
        limit: int,
        offset: int,
    ) -> OperationalSLODefinitionPage:
        return await self._runtime.list_slo_definitions(
            query=OperationalSLODefinitionQuery(
                metric_name=metric_name,
                enabled=enabled,
                limit=limit,
                offset=offset,
            ),
            expected_tenant_id=tenant_id,
        )

    async def evaluate_alerts(
        self,
        *,
        tenant_id: str,
        window_start: datetime,
        window_end: datetime,
    ) -> OperationalAlertPage:
        return await self._runtime.evaluate_alerts(
            query=OperationalMetricsQuery(
                window_start=window_start,
                window_end=window_end,
            ),
            expected_tenant_id=tenant_id,
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
        parent_span_id: OperationalTraceSpanId | None,
        error: str | None,
        attributes: Mapping[str, Any],
    ) -> OperationalTraceSpanRecord:
        try:
            record = await self._runtime.record_trace_span(
                tenant_id=tenant_id,
                trace_id=trace_id,
                span_name=span_name,
                substrate=substrate,
                operation=operation,
                started_at=started_at,
                ended_at=ended_at,
                status=status,
                parent_span_id=parent_span_id,
                error=error,
                attributes=attributes,
            )
            await self._session.commit()
            return record
        except Exception:
            await self._session.rollback()
            raise

    async def get_trace_span(
        self,
        *,
        tenant_id: str,
        span_id: OperationalTraceSpanId,
    ) -> OperationalTraceSpanRecord | None:
        return await self._runtime.get_trace_span(
            span_id=span_id,
            expected_tenant_id=tenant_id,
        )

    async def list_trace_spans(
        self,
        *,
        tenant_id: str,
        trace_id: str | None,
        limit: int,
        offset: int,
    ) -> OperationalTraceSpanPage:
        return await self._runtime.list_trace_spans(
            query=OperationalTraceSpanQuery(
                trace_id=trace_id,
                limit=limit,
                offset=offset,
            ),
            expected_tenant_id=tenant_id,
        )


__all__ = ["OperationalObservabilityService"]
