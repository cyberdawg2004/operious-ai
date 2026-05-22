"""In-memory operational observability persistence."""

from __future__ import annotations

from datetime import datetime

from app.boundary.enums import (
    BoundaryNormalizationStatus,
    BoundaryReplayDisposition,
)
from app.boundary.persistence.records import BoundaryIngressRecord
from app.escalation.persistence.records import EscalationRecord
from app.execution.enums import ExecutionState
from app.execution.persistence.records import ExecutionRecord
from app.governance.persistence.records import GovernanceDecisionRecord
from app.observability.enums import OperationalMetricName
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
from app.qa.persistence.records import QAScoreRecord


class InMemoryOperationalObservabilityPersistence:
    """Reference backend for deterministic observability tests."""

    def __init__(
        self,
        *,
        boundary_ingress_records: tuple[BoundaryIngressRecord, ...] = (),
        governance_decision_records: tuple[GovernanceDecisionRecord, ...] = (),
        execution_records: tuple[ExecutionRecord, ...] = (),
        qa_score_records: tuple[QAScoreRecord, ...] = (),
        escalation_records: tuple[EscalationRecord, ...] = (),
    ) -> None:
        self._boundary_ingress_records = boundary_ingress_records
        self._governance_decision_records = governance_decision_records
        self._execution_records = execution_records
        self._qa_score_records = qa_score_records
        self._escalation_records = escalation_records
        self._slo_definitions: dict[
            OperationalSLODefinitionId, OperationalSLODefinitionRecord
        ] = {}
        self._trace_spans: dict[
            OperationalTraceSpanId, OperationalTraceSpanRecord
        ] = {}

    async def read_metrics(
        self,
        query: OperationalMetricsQuery,
        *,
        expected_tenant_id: str,
    ) -> OperationalMetricsSnapshotRecord:
        tickets = tuple(
            record
            for record in self._boundary_ingress_records
            if record.tenant_id == expected_tenant_id
            and query.window_start <= record.received_at < query.window_end
            and record.normalization_status is BoundaryNormalizationStatus.OK
            and record.replay_disposition is BoundaryReplayDisposition.NEW
        )
        governance = tuple(
            record.decision
            for record in self._governance_decision_records
            if record.tenant_id == expected_tenant_id
            and query.window_start <= _parse_dt(record.decided_at) < query.window_end
        )
        executions = tuple(
            ExecutionLatencySample(
                requested_at=record.requested_at,
                completed_at=record.completed_at,
                failed_at=record.failed_at,
                state=_state_value(record.state),
            )
            for record in self._execution_records
            if record.tenant_id == expected_tenant_id
            and query.window_start <= record.requested_at < query.window_end
        )
        qa_scores = tuple(
            record.overall_score
            for record in self._qa_score_records
            if record.tenant_id == expected_tenant_id
            and query.window_start <= _parse_dt(record.scored_at) < query.window_end
        )
        escalation_count = sum(
            1
            for record in self._escalation_records
            if record.tenant_id == expected_tenant_id
            and query.window_start <= _parse_dt(record.created_at) < query.window_end
        )
        dlq_count = sum(
            1
            for record in self._execution_records
            if record.tenant_id == expected_tenant_id
            and _state_value(record.state) == ExecutionState.DEAD_LETTERED.value
            and record.failed_at is not None
            and query.window_start <= record.failed_at < query.window_end
        )
        return build_metrics_snapshot(
            tenant_id=expected_tenant_id,
            window_start=query.window_start,
            window_end=query.window_end,
            ticket_throughput=len(tickets),
            governance_decisions=governance,
            executions=executions,
            qa_scores=qa_scores,
            escalation_count=escalation_count,
            dlq_count=dlq_count,
        )

    async def list_dead_letter_executions(
        self,
        query: DeadLetterExecutionQuery,
        *,
        expected_tenant_id: str,
    ) -> DeadLetterExecutionPage:
        rows = [
            _dead_letter_from_execution(record)
            for record in self._execution_records
            if record.tenant_id == expected_tenant_id
            and _state_value(record.state) == ExecutionState.DEAD_LETTERED.value
        ]
        if query.execution_id is not None:
            rows = [row for row in rows if row.execution_id == query.execution_id]
        rows.sort(
            key=lambda row: (
                row.failed_at or row.requested_at,
                row.execution_id,
            ),
            reverse=True,
        )
        total = len(rows)
        sliced = rows[query.offset : query.offset + query.limit]
        return DeadLetterExecutionPage(
            items=tuple(sliced),
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
        self._slo_definitions[record.slo_id] = record
        return record

    async def get_slo_definition(
        self,
        slo_id: OperationalSLODefinitionId,
        *,
        expected_tenant_id: str,
    ) -> OperationalSLODefinitionRecord | None:
        record = self._slo_definitions.get(slo_id)
        if record is None or record.tenant_id != expected_tenant_id:
            return None
        return record

    async def list_slo_definitions(
        self,
        query: OperationalSLODefinitionQuery,
        *,
        expected_tenant_id: str,
    ) -> OperationalSLODefinitionPage:
        rows = [
            record
            for record in self._slo_definitions.values()
            if record.tenant_id == expected_tenant_id
        ]
        if query.slo_id is not None:
            rows = [record for record in rows if record.slo_id == query.slo_id]
        if query.metric_name is not None:
            rows = [
                record for record in rows if record.metric_name is query.metric_name
            ]
        if query.enabled is not None:
            rows = [record for record in rows if record.enabled is query.enabled]
        rows.sort(
            key=lambda record: (
                record.metric_name.value,
                record.window_minutes,
                record.severity.value,
            )
        )
        total = len(rows)
        sliced = rows[query.offset : query.offset + query.limit]
        return OperationalSLODefinitionPage(
            items=tuple(sliced),
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
        existing = self._trace_spans.get(record.span_id)
        if existing is not None:
            return existing
        self._trace_spans[record.span_id] = record
        return record

    async def get_trace_span(
        self,
        span_id: OperationalTraceSpanId,
        *,
        expected_tenant_id: str,
    ) -> OperationalTraceSpanRecord | None:
        record = self._trace_spans.get(span_id)
        if record is None or record.tenant_id != expected_tenant_id:
            return None
        return record

    async def list_trace_spans(
        self,
        query: OperationalTraceSpanQuery,
        *,
        expected_tenant_id: str,
    ) -> OperationalTraceSpanPage:
        rows = [
            record
            for record in self._trace_spans.values()
            if record.tenant_id == expected_tenant_id
        ]
        if query.span_id is not None:
            rows = [record for record in rows if record.span_id == query.span_id]
        if query.trace_id is not None:
            rows = [record for record in rows if record.trace_id == query.trace_id]
        rows.sort(key=lambda record: (record.started_at, str(record.span_id)))
        total = len(rows)
        sliced = rows[query.offset : query.offset + query.limit]
        return OperationalTraceSpanPage(
            items=tuple(sliced),
            total=total,
            offset=query.offset,
        )


def _parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _state_value(value: object) -> str:
    if isinstance(value, str):
        return value
    return getattr(value, "value", str(value))


def _dead_letter_from_execution(record: ExecutionRecord) -> DeadLetterExecutionRecord:
    return DeadLetterExecutionRecord(
        execution_id=str(record.execution_id),
        tenant_id=record.tenant_id,
        kind=_state_value(record.kind),
        dispatch_id=record.dispatch_id,
        session_id=record.session_id,
        state=_state_value(record.state),
        attempt_count=record.attempt_count,
        requested_at=record.requested_at,
        failed_at=record.failed_at,
        worker_id=record.worker_id,
        error=record.error,
        metadata=dict(record.metadata),
    )


def _assert_tenant(record_tenant_id: str, expected_tenant_id: str) -> None:
    if record_tenant_id != expected_tenant_id:
        raise ValueError("record tenant_id does not match expected_tenant_id")


__all__ = ["InMemoryOperationalObservabilityPersistence"]
