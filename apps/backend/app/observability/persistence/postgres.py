"""Postgres operational observability persistence."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import case, func, select, update
from sqlalchemy.exc import IntegrityError

from app.boundary.db.models import BoundaryIngressRow
from app.boundary.enums import (
    BoundaryNormalizationStatus,
    BoundaryReplayDisposition,
)
from app.escalation.db.models import EscalationRecordRow
from app.execution.db.models import ExecutionRow
from app.execution.enums import ExecutionState
from app.observability.db.models import (
    OperationalSLODefinitionRow,
    OperationalTraceSpanRow,
)
from app.observability.enums import (
    AlertSeverity,
    AlertThresholdOperator,
    OperationalMetricName,
    OperationalTraceStatus,
)
from app.observability.identity import (
    OperationalSLODefinitionId,
    OperationalTraceSpanId,
)
from app.observability.persistence.models import (
    DeadLetterExecutionPage,
    DeadLetterExecutionQuery,
    InboundNormalizationDeadLetterPage,
    InboundNormalizationDeadLetterQuery,
    OperationalMetricsQuery,
    OperationalSLODefinitionPage,
    OperationalSLODefinitionQuery,
    OperationalTraceSpanPage,
    OperationalTraceSpanQuery,
    StuckExecutionAlertPage,
    StuckExecutionAlertQuery,
)
from app.observability.persistence.records import (
    DeadLetterExecutionRecord,
    InboundNormalizationDeadLetterRecord,
    OperationalMetricsSnapshotRecord,
    OperationalSLODefinitionRecord,
    OperationalTraceSpanRecord,
    QAScoreBucketRecord,
    StuckExecutionAlertRecord,
)
from app.governance.db.models import GovernanceDecisionRow
from app.qa.db.models import QAScoreRow
from app.repositories.base import BaseRepository
from app.repositories.pagination import count_matching_rows, fetch_scalar_page
from app.tenant.db.models import TenantRow


class PostgresOperationalObservabilityPersistence(BaseRepository):
    """Postgres-backed tenant operational observability read/config store."""

    async def read_metrics(
        self,
        query: OperationalMetricsQuery,
        *,
        expected_tenant_id: str,
    ) -> OperationalMetricsSnapshotRecord:
        ticket_stmt = select(BoundaryIngressRow.ingress_id).where(
            BoundaryIngressRow.tenant_id == expected_tenant_id,
            BoundaryIngressRow.received_at >= query.window_start,
            BoundaryIngressRow.received_at < query.window_end,
            BoundaryIngressRow.normalization_status
            == BoundaryNormalizationStatus.OK.value,
            BoundaryIngressRow.replay_disposition
            == BoundaryReplayDisposition.NEW.value,
        )
        ticket_throughput = await count_matching_rows(
            self.session,
            ticket_stmt,
        )
        governance_count, governance_deny_count = (
            await self.session.execute(
                select(
                    func.count(GovernanceDecisionRow.decision_id),
                    func.coalesce(
                        func.sum(
                            case(
                                (
                                    GovernanceDecisionRow.decision == "deny",
                                    1,
                                ),
                                else_=0,
                            )
                        ),
                        0,
                    ),
                ).where(
                    GovernanceDecisionRow.tenant_id == expected_tenant_id,
                    GovernanceDecisionRow.decided_at >= query.window_start,
                    GovernanceDecisionRow.decided_at < query.window_end,
                )
            )
        ).one()
        execution_count, completed_execution_count = (
            await self.session.execute(
                select(
                    func.count(ExecutionRow.execution_id),
                    func.coalesce(
                        func.sum(
                            case(
                                (ExecutionRow.completed_at.is_not(None), 1),
                                else_=0,
                            )
                        ),
                        0,
                    ),
                ).where(
                    ExecutionRow.tenant_id == expected_tenant_id,
                    ExecutionRow.requested_at >= query.window_start,
                    ExecutionRow.requested_at < query.window_end,
                )
            )
        ).one()
        ended_at = func.coalesce(
            ExecutionRow.completed_at,
            ExecutionRow.failed_at,
        )
        latency_ms = func.extract(
            "epoch",
            ended_at - ExecutionRow.requested_at,
        ) * 1000.0
        latency_avg, latency_p50, latency_p95 = (
            await self.session.execute(
                select(
                    func.avg(latency_ms),
                    func.percentile_disc(0.50).within_group(latency_ms),
                    func.percentile_disc(0.95).within_group(latency_ms),
                ).where(
                    ExecutionRow.tenant_id == expected_tenant_id,
                    ExecutionRow.requested_at >= query.window_start,
                    ExecutionRow.requested_at < query.window_end,
                    ended_at.is_not(None),
                )
            )
        ).one()
        score = func.least(func.greatest(QAScoreRow.overall_score, 0.0), 1.0)
        qa_row = (
            await self.session.execute(
                select(
                    func.count(QAScoreRow.score_id),
                    func.avg(QAScoreRow.overall_score),
                    func.coalesce(
                        func.sum(
                            case(((score >= 0.0) & (score < 0.2), 1), else_=0)
                        ),
                        0,
                    ),
                    func.coalesce(
                        func.sum(
                            case(((score >= 0.2) & (score < 0.4), 1), else_=0)
                        ),
                        0,
                    ),
                    func.coalesce(
                        func.sum(
                            case(((score >= 0.4) & (score < 0.6), 1), else_=0)
                        ),
                        0,
                    ),
                    func.coalesce(
                        func.sum(
                            case(((score >= 0.6) & (score < 0.8), 1), else_=0)
                        ),
                        0,
                    ),
                    func.coalesce(
                        func.sum(case((score >= 0.8, 1), else_=0)),
                        0,
                    ),
                ).where(
                    QAScoreRow.tenant_id == expected_tenant_id,
                    QAScoreRow.scored_at >= query.window_start,
                    QAScoreRow.scored_at < query.window_end,
                )
            )
        ).one()
        escalation_count = await count_matching_rows(
            self.session,
            select(EscalationRecordRow.escalation_id).where(
                EscalationRecordRow.tenant_id == expected_tenant_id,
                EscalationRecordRow.created_at >= query.window_start,
                EscalationRecordRow.created_at < query.window_end,
            ),
        )
        dlq_count = await count_matching_rows(
            self.session,
            select(ExecutionRow.execution_id).where(
                ExecutionRow.tenant_id == expected_tenant_id,
                ExecutionRow.state == ExecutionState.DEAD_LETTERED.value,
                ExecutionRow.failed_at.is_not(None),
                ExecutionRow.failed_at >= query.window_start,
                ExecutionRow.failed_at < query.window_end,
            ),
        )
        qa_count = int(qa_row[0] or 0)
        qa_average = _optional_float(qa_row[1])
        qa_distribution = (
            QAScoreBucketRecord(0.0, 0.2, int(qa_row[2] or 0)),
            QAScoreBucketRecord(0.2, 0.4, int(qa_row[3] or 0)),
            QAScoreBucketRecord(0.4, 0.6, int(qa_row[4] or 0)),
            QAScoreBucketRecord(0.6, 0.8, int(qa_row[5] or 0)),
            QAScoreBucketRecord(0.8, 1.0, int(qa_row[6] or 0)),
        )
        return OperationalMetricsSnapshotRecord(
            tenant_id=expected_tenant_id,
            window_start=query.window_start,
            window_end=query.window_end,
            ticket_throughput=ticket_throughput,
            governance_decision_count=int(governance_count or 0),
            governance_deny_count=int(governance_deny_count or 0),
            governance_deny_rate=_rate(
                int(governance_deny_count or 0),
                int(governance_count or 0),
            ),
            execution_count=int(execution_count or 0),
            completed_execution_count=int(completed_execution_count or 0),
            execution_latency_ms_avg=_optional_float(latency_avg),
            execution_latency_ms_p50=_optional_float(latency_p50),
            execution_latency_ms_p95=_optional_float(latency_p95),
            qa_score_count=qa_count,
            qa_score_average=qa_average,
            qa_score_distribution=qa_distribution,
            escalation_count=escalation_count,
            escalation_rate=_rate(escalation_count, ticket_throughput),
            dlq_count=dlq_count,
        )

    async def list_dead_letter_executions(
        self,
        query: DeadLetterExecutionQuery,
        *,
        expected_tenant_id: str,
    ) -> DeadLetterExecutionPage:
        stmt = select(ExecutionRow).where(
            ExecutionRow.tenant_id == expected_tenant_id,
            ExecutionRow.state == ExecutionState.DEAD_LETTERED.value,
        )
        if query.execution_id is not None:
            stmt = stmt.where(ExecutionRow.execution_id == query.execution_id)
        stmt = stmt.order_by(
            ExecutionRow.failed_at.desc(),
            ExecutionRow.requested_at.desc(),
            ExecutionRow.execution_id,
        )
        page = await fetch_scalar_page(
            self.session,
            stmt,
            limit=query.limit,
            offset=query.offset,
        )
        return DeadLetterExecutionPage(
            items=tuple(_dead_letter_row_to_record(row) for row in page.items),
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )

    async def list_stuck_execution_alerts(
        self,
        query: StuckExecutionAlertQuery,
        *,
        expected_tenant_id: str,
    ) -> StuckExecutionAlertPage:
        stmt = (
            select(ExecutionRow)
            .where(
                ExecutionRow.tenant_id == expected_tenant_id,
                ExecutionRow.state == ExecutionState.CLAIMED.value,
                ExecutionRow.claimed_at.is_not(None),
                ExecutionRow.claimed_at <= query.claimed_before_or_at,
            )
            .order_by(ExecutionRow.claimed_at, ExecutionRow.execution_id)
        )
        page = await fetch_scalar_page(
            self.session,
            stmt,
            limit=query.limit,
            offset=query.offset,
        )
        return StuckExecutionAlertPage(
            items=tuple(
                _stuck_alert_row_to_record(
                    row,
                    claimed_before_or_at=query.claimed_before_or_at,
                )
                for row in page.items
            ),
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )

    async def list_inbound_normalization_dead_letters(
        self,
        query: InboundNormalizationDeadLetterQuery,
        *,
        expected_tenant_id: str,
    ) -> InboundNormalizationDeadLetterPage:
        stmt = select(BoundaryIngressRow).where(
            BoundaryIngressRow.tenant_id == expected_tenant_id,
            BoundaryIngressRow.normalization_status
            != BoundaryNormalizationStatus.OK.value,
            BoundaryIngressRow.error.is_not(None),
        )
        if query.normalization_status is not None:
            stmt = stmt.where(
                BoundaryIngressRow.normalization_status
                == query.normalization_status
            )
        stmt = stmt.order_by(
            BoundaryIngressRow.received_at.desc(),
            BoundaryIngressRow.ingress_id,
        )
        page = await fetch_scalar_page(
            self.session,
            stmt,
            limit=query.limit,
            offset=query.offset,
        )
        return InboundNormalizationDeadLetterPage(
            items=tuple(
                _inbound_dead_letter_row_to_record(row) for row in page.items
            ),
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )

    async def save_slo_definition(
        self,
        record: OperationalSLODefinitionRecord,
        *,
        expected_tenant_id: str,
    ) -> OperationalSLODefinitionRecord:
        _assert_tenant(record.tenant_id, expected_tenant_id)
        await self._ensure_tenant(expected_tenant_id)
        existing = await self._slo_row(record.slo_id, expected_tenant_id)
        try:
            async with self.session.begin_nested():
                if existing is None:
                    self.session.add(_slo_record_to_row(record))
                else:
                    await self.session.execute(
                        update(OperationalSLODefinitionRow)
                        .where(
                            OperationalSLODefinitionRow.slo_id == record.slo_id,
                            OperationalSLODefinitionRow.tenant_id
                            == expected_tenant_id,
                        )
                        .values(
                            threshold_operator=record.threshold_operator.value,
                            threshold_value=record.threshold_value,
                            enabled=record.enabled,
                            updated_at=record.updated_at,
                            metadata_json=dict(record.metadata),
                        )
                    )
        except IntegrityError:
            existing = await self._slo_row(record.slo_id, expected_tenant_id)
            if existing is not None:
                return _slo_row_to_record(existing)
            raise
        stored = await self._slo_row(record.slo_id, expected_tenant_id)
        return record if stored is None else _slo_row_to_record(stored)

    async def get_slo_definition(
        self,
        slo_id: OperationalSLODefinitionId,
        *,
        expected_tenant_id: str,
    ) -> OperationalSLODefinitionRecord | None:
        row = await self._slo_row(slo_id, expected_tenant_id)
        return None if row is None else _slo_row_to_record(row)

    async def list_slo_definitions(
        self,
        query: OperationalSLODefinitionQuery,
        *,
        expected_tenant_id: str,
    ) -> OperationalSLODefinitionPage:
        stmt = select(OperationalSLODefinitionRow).where(
            OperationalSLODefinitionRow.tenant_id == expected_tenant_id
        )
        if query.slo_id is not None:
            stmt = stmt.where(OperationalSLODefinitionRow.slo_id == query.slo_id)
        if query.metric_name is not None:
            stmt = stmt.where(
                OperationalSLODefinitionRow.metric_name == query.metric_name.value
            )
        if query.enabled is not None:
            stmt = stmt.where(OperationalSLODefinitionRow.enabled == query.enabled)
        stmt = stmt.order_by(
            OperationalSLODefinitionRow.metric_name,
            OperationalSLODefinitionRow.window_minutes,
            OperationalSLODefinitionRow.severity,
        )
        page = await fetch_scalar_page(
            self.session,
            stmt,
            limit=query.limit,
            offset=query.offset,
        )
        return OperationalSLODefinitionPage(
            items=tuple(_slo_row_to_record(row) for row in page.items),
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )

    async def save_trace_span(
        self,
        record: OperationalTraceSpanRecord,
        *,
        expected_tenant_id: str,
    ) -> OperationalTraceSpanRecord:
        _assert_tenant(record.tenant_id, expected_tenant_id)
        await self._ensure_tenant(expected_tenant_id)
        try:
            async with self.session.begin_nested():
                self.session.add(_trace_span_record_to_row(record))
        except IntegrityError:
            existing = await self._trace_span_row(
                record.span_id,
                expected_tenant_id,
            )
            if existing is not None:
                return _trace_span_row_to_record(existing)
            raise
        return record

    async def get_trace_span(
        self,
        span_id: OperationalTraceSpanId,
        *,
        expected_tenant_id: str,
    ) -> OperationalTraceSpanRecord | None:
        row = await self._trace_span_row(span_id, expected_tenant_id)
        return None if row is None else _trace_span_row_to_record(row)

    async def list_trace_spans(
        self,
        query: OperationalTraceSpanQuery,
        *,
        expected_tenant_id: str,
    ) -> OperationalTraceSpanPage:
        stmt = select(OperationalTraceSpanRow).where(
            OperationalTraceSpanRow.tenant_id == expected_tenant_id
        )
        if query.span_id is not None:
            stmt = stmt.where(OperationalTraceSpanRow.span_id == query.span_id)
        if query.trace_id is not None:
            stmt = stmt.where(OperationalTraceSpanRow.trace_id == query.trace_id)
        stmt = stmt.order_by(
            OperationalTraceSpanRow.started_at,
            OperationalTraceSpanRow.span_id,
        )
        page = await fetch_scalar_page(
            self.session,
            stmt,
            limit=query.limit,
            offset=query.offset,
        )
        return OperationalTraceSpanPage(
            items=tuple(_trace_span_row_to_record(row) for row in page.items),
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )

    async def _ensure_tenant(self, tenant_id: str) -> None:
        await self.session.merge(TenantRow(tenant_id=tenant_id))

    async def _slo_row(
        self,
        slo_id: OperationalSLODefinitionId,
        expected_tenant_id: str,
    ) -> OperationalSLODefinitionRow | None:
        stmt = select(OperationalSLODefinitionRow).where(
            OperationalSLODefinitionRow.slo_id == slo_id,
            OperationalSLODefinitionRow.tenant_id == expected_tenant_id,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def _trace_span_row(
        self,
        span_id: OperationalTraceSpanId,
        expected_tenant_id: str,
    ) -> OperationalTraceSpanRow | None:
        stmt = select(OperationalTraceSpanRow).where(
            OperationalTraceSpanRow.span_id == span_id,
            OperationalTraceSpanRow.tenant_id == expected_tenant_id,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return round(float(value), 6)


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 6)


def _dead_letter_row_to_record(row: ExecutionRow) -> DeadLetterExecutionRecord:
    return DeadLetterExecutionRecord(
        execution_id=str(row.execution_id),
        tenant_id=row.tenant_id,
        kind=row.kind,
        dispatch_id=row.dispatch_id,
        session_id=row.session_id,
        state=row.state,
        attempt_count=row.attempt_count,
        requested_at=row.requested_at,
        failed_at=row.failed_at,
        worker_id=row.worker_id,
        error=row.error,
        metadata=dict(row.metadata_json or {}),
    )


_STUCK_ALERT_NAMESPACE = uuid.UUID("4897a7e1-62ed-5ed7-a1c6-eaa1aee32c01")
_INBOUND_DLQ_NAMESPACE = uuid.UUID("4897a7e1-62ed-5ed7-a1c6-eaa1aee32c02")


def _stuck_alert_row_to_record(
    row: ExecutionRow,
    *,
    claimed_before_or_at: datetime,
) -> StuckExecutionAlertRecord:
    alert_id = uuid.uuid5(
        _STUCK_ALERT_NAMESPACE,
        f"{row.tenant_id}|{row.execution_id}|{claimed_before_or_at.isoformat()}",
    )
    return StuckExecutionAlertRecord(
        alert_id=str(alert_id),
        tenant_id=row.tenant_id,
        execution_id=str(row.execution_id),
        reason="execution_claim_exceeded_lease",
        claimed_at=row.claimed_at,
        worker_id=row.worker_id,
        metadata={"state": row.state},
    )


def _inbound_dead_letter_row_to_record(
    row: BoundaryIngressRow,
) -> InboundNormalizationDeadLetterRecord:
    tenant_id = row.tenant_id or ""
    dead_letter_id = uuid.uuid5(
        _INBOUND_DLQ_NAMESPACE,
        f"{tenant_id}|{row.ingress_id}|{row.normalization_status}",
    )
    return InboundNormalizationDeadLetterRecord(
        dead_letter_id=str(dead_letter_id),
        tenant_id=tenant_id,
        ingress_id=str(row.ingress_id),
        normalization_status=row.normalization_status,
        error=row.error,
        received_at=row.received_at,
        metadata=dict(row.metadata_json or {}),
    )


def _slo_record_to_row(
    record: OperationalSLODefinitionRecord,
) -> OperationalSLODefinitionRow:
    return OperationalSLODefinitionRow(
        slo_id=record.slo_id,
        tenant_id=record.tenant_id,
        metric_name=record.metric_name.value,
        threshold_operator=record.threshold_operator.value,
        threshold_value=record.threshold_value,
        window_minutes=record.window_minutes,
        severity=record.severity.value,
        enabled=record.enabled,
        created_at=record.created_at,
        updated_at=record.updated_at,
        metadata_json=dict(record.metadata),
    )


def _slo_row_to_record(
    row: OperationalSLODefinitionRow,
) -> OperationalSLODefinitionRecord:
    return OperationalSLODefinitionRecord(
        slo_id=OperationalSLODefinitionId(row.slo_id),
        tenant_id=row.tenant_id,
        metric_name=OperationalMetricName(row.metric_name),
        threshold_operator=AlertThresholdOperator(row.threshold_operator),
        threshold_value=row.threshold_value,
        window_minutes=row.window_minutes,
        severity=AlertSeverity(row.severity),
        enabled=row.enabled,
        created_at=row.created_at,
        updated_at=row.updated_at,
        metadata=dict(row.metadata_json or {}),
    )


def _trace_span_record_to_row(
    record: OperationalTraceSpanRecord,
) -> OperationalTraceSpanRow:
    return OperationalTraceSpanRow(
        span_id=record.span_id,
        tenant_id=record.tenant_id,
        trace_id=record.trace_id,
        parent_span_id=record.parent_span_id,
        span_name=record.span_name,
        substrate=record.substrate,
        operation=record.operation,
        started_at=record.started_at,
        ended_at=record.ended_at,
        latency_ms=record.latency_ms,
        status=record.status.value,
        error=record.error,
        attributes=dict(record.attributes),
        created_at=record.created_at or record.started_at,
    )


def _trace_span_row_to_record(
    row: OperationalTraceSpanRow,
) -> OperationalTraceSpanRecord:
    return OperationalTraceSpanRecord(
        span_id=OperationalTraceSpanId(row.span_id),
        tenant_id=row.tenant_id,
        trace_id=row.trace_id,
        parent_span_id=(
            OperationalTraceSpanId(row.parent_span_id)
            if row.parent_span_id is not None
            else None
        ),
        span_name=row.span_name,
        substrate=row.substrate,
        operation=row.operation,
        started_at=row.started_at,
        ended_at=row.ended_at,
        latency_ms=row.latency_ms,
        status=OperationalTraceStatus(row.status),
        error=row.error,
        attributes=dict(row.attributes or {}),
        created_at=row.created_at,
    )


def _assert_tenant(record_tenant_id: str, expected_tenant_id: str) -> None:
    if record_tenant_id != expected_tenant_id:
        raise ValueError("record tenant_id does not match expected_tenant_id")


__all__ = ["PostgresOperationalObservabilityPersistence"]
