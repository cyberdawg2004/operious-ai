"""Postgres operational observability persistence."""

from __future__ import annotations

from sqlalchemy import select, update
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
from app.observability.persistence.calculations import (
    ExecutionLatencySample,
    build_metrics_snapshot,
)
from app.observability.persistence.models import (
    DeadLetterExecutionPage,
    DeadLetterExecutionQuery,
    OperationalMetricsQuery,
    OperationalSLODefinitionPage,
    OperationalSLODefinitionQuery,
    OperationalTraceSpanPage,
    OperationalTraceSpanQuery,
)
from app.observability.persistence.records import (
    DeadLetterExecutionRecord,
    OperationalMetricsSnapshotRecord,
    OperationalSLODefinitionRecord,
    OperationalTraceSpanRecord,
)
from app.governance.db.models import GovernanceDecisionRow
from app.qa.db.models import QAScoreRow
from app.repositories.base import BaseRepository
from app.tenant.db.models import TenantRow


class PostgresOperationalObservabilityPersistence(BaseRepository):
    """Postgres-backed tenant operational observability read/config store."""

    async def read_metrics(
        self,
        query: OperationalMetricsQuery,
        *,
        expected_tenant_id: str,
    ) -> OperationalMetricsSnapshotRecord:
        ticket_rows = list(
            (
                await self.session.execute(
                    select(BoundaryIngressRow.ingress_id).where(
                        BoundaryIngressRow.tenant_id == expected_tenant_id,
                        BoundaryIngressRow.received_at >= query.window_start,
                        BoundaryIngressRow.received_at < query.window_end,
                        BoundaryIngressRow.normalization_status
                        == BoundaryNormalizationStatus.OK.value,
                        BoundaryIngressRow.replay_disposition
                        == BoundaryReplayDisposition.NEW.value,
                    )
                )
            ).all()
        )
        governance_rows = list(
            (
                await self.session.execute(
                    select(GovernanceDecisionRow.decision).where(
                        GovernanceDecisionRow.tenant_id == expected_tenant_id,
                        GovernanceDecisionRow.decided_at >= query.window_start,
                        GovernanceDecisionRow.decided_at < query.window_end,
                    )
                )
            ).scalars().all()
        )
        execution_rows = list(
            (
                await self.session.execute(
                    select(ExecutionRow).where(
                        ExecutionRow.tenant_id == expected_tenant_id,
                        ExecutionRow.requested_at >= query.window_start,
                        ExecutionRow.requested_at < query.window_end,
                    )
                )
            ).scalars().all()
        )
        qa_rows = list(
            (
                await self.session.execute(
                    select(QAScoreRow.overall_score).where(
                        QAScoreRow.tenant_id == expected_tenant_id,
                        QAScoreRow.scored_at >= query.window_start,
                        QAScoreRow.scored_at < query.window_end,
                    )
                )
            ).scalars().all()
        )
        escalation_rows = list(
            (
                await self.session.execute(
                    select(EscalationRecordRow.escalation_id).where(
                        EscalationRecordRow.tenant_id == expected_tenant_id,
                        EscalationRecordRow.created_at >= query.window_start,
                        EscalationRecordRow.created_at < query.window_end,
                    )
                )
            ).all()
        )
        dlq_rows = list(
            (
                await self.session.execute(
                    select(ExecutionRow.execution_id).where(
                        ExecutionRow.tenant_id == expected_tenant_id,
                        ExecutionRow.state == ExecutionState.DEAD_LETTERED.value,
                        ExecutionRow.failed_at.is_not(None),
                        ExecutionRow.failed_at >= query.window_start,
                        ExecutionRow.failed_at < query.window_end,
                    )
                )
            ).all()
        )
        return build_metrics_snapshot(
            tenant_id=expected_tenant_id,
            window_start=query.window_start,
            window_end=query.window_end,
            ticket_throughput=len(ticket_rows),
            governance_decisions=tuple(governance_rows),
            executions=tuple(
                ExecutionLatencySample(
                    requested_at=row.requested_at,
                    completed_at=row.completed_at,
                    failed_at=row.failed_at,
                    state=row.state,
                )
                for row in execution_rows
            ),
            qa_scores=tuple(float(score) for score in qa_rows),
            escalation_count=len(escalation_rows),
            dlq_count=len(dlq_rows),
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
        rows = list((await self.session.execute(stmt)).scalars().all())
        total = len(rows)
        sliced = rows[query.offset : query.offset + query.limit]
        return DeadLetterExecutionPage(
            items=tuple(_dead_letter_row_to_record(row) for row in sliced),
            total=total,
            offset=query.offset,
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
        rows = list((await self.session.execute(stmt)).scalars().all())
        total = len(rows)
        sliced = rows[query.offset : query.offset + query.limit]
        return OperationalSLODefinitionPage(
            items=tuple(_slo_row_to_record(row) for row in sliced),
            total=total,
            offset=query.offset,
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
        rows = list((await self.session.execute(stmt)).scalars().all())
        total = len(rows)
        sliced = rows[query.offset : query.offset + query.limit]
        return OperationalTraceSpanPage(
            items=tuple(_trace_span_row_to_record(row) for row in sliced),
            total=total,
            offset=query.offset,
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
