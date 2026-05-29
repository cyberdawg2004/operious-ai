"""Phase 6-A operational observability runtime tests."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.boundary.enums import (
    BoundaryDirection,
    BoundaryMessageType,
    BoundaryNormalizationStatus,
    BoundaryReplayDisposition,
    BoundarySourceType,
)
from app.boundary.identity import (
    BoundaryEventId,
    BoundaryIngressId,
)
from app.boundary.persistence.records import BoundaryIngressRecord
from app.escalation.persistence.records import EscalationRecord
from app.execution.enums import ExecutionKind, ExecutionState
from app.execution.identity import ExecutionId
from app.execution.persistence.records import ExecutionRecord
from app.governance.persistence.records import GovernanceDecisionRecord
from app.observability.enums import (
    AlertSeverity,
    AlertThresholdOperator,
    OperationalMetricName,
    OperationalTraceStatus,
)
from app.observability.persistence import (
    DeadLetterExecutionQuery,
    InMemoryOperationalObservabilityPersistence,
    OperationalMetricsQuery,
    OperationalTraceSpanQuery,
)
from app.observability.persistence.calculations import (
    ExecutionLatencySample,
    build_metrics_snapshot,
)
from app.observability.runtime import OperationalObservabilityRuntime
from app.qa.persistence.records import QAScoreRecord

_BASE = datetime(2026, 5, 22, 8, tzinfo=timezone.utc)


def _dt(minutes: int) -> datetime:
    return _BASE + timedelta(minutes=minutes)


@pytest.mark.asyncio
async def test_metrics_are_tenant_scoped_and_deterministic() -> None:
    runtime = _runtime()
    query = OperationalMetricsQuery(window_start=_dt(0), window_end=_dt(60))

    first = await runtime.read_metrics(
        query=query,
        expected_tenant_id="tenant-acme",
    )
    second = await runtime.read_metrics(
        query=query,
        expected_tenant_id="tenant-acme",
    )
    other = await runtime.read_metrics(
        query=query,
        expected_tenant_id="tenant-other",
    )

    assert first == second
    assert first.ticket_throughput == 2
    assert first.governance_decision_count == 2
    assert first.governance_deny_count == 1
    assert first.governance_deny_rate == 0.5
    assert first.execution_count == 2
    assert first.completed_execution_count == 1
    assert first.execution_latency_ms_avg == 750.0
    assert first.execution_latency_ms_p50 == 500.0
    assert first.execution_latency_ms_p95 == 1000.0
    assert first.execution_latency_ms_p99 is None
    assert first.qa_score_count == 2
    assert first.qa_score_average == 0.65
    assert [bucket.count for bucket in first.qa_score_distribution] == [
        0,
        0,
        1,
        0,
        1,
    ]
    assert first.escalation_count == 1
    assert first.escalation_rate == 0.5
    assert first.dlq_count == 1
    assert other.ticket_throughput == 1
    assert other.governance_deny_rate == 1.0
    assert other.dlq_count == 0


@pytest.mark.asyncio
async def test_dead_letter_read_surface_is_tenant_scoped() -> None:
    runtime = _runtime()
    own = await runtime.list_dead_letters(
        query=DeadLetterExecutionQuery(),
        expected_tenant_id="tenant-acme",
    )
    other = await runtime.list_dead_letters(
        query=DeadLetterExecutionQuery(),
        expected_tenant_id="tenant-other",
    )
    cross = await runtime.list_dead_letters(
        query=DeadLetterExecutionQuery(
            execution_id="00000000-0000-0000-0000-000000006a02"
        ),
        expected_tenant_id="tenant-other",
    )

    assert own.total == 1
    assert own.items[0].state == "dead_lettered"
    assert own.items[0].tenant_id == "tenant-acme"
    assert other.total == 0
    assert cross.total == 0


def test_execution_latency_p99_requires_100_samples() -> None:
    small = build_metrics_snapshot(
        tenant_id="tenant-acme",
        window_start=_dt(0),
        window_end=_dt(60),
        ticket_throughput=0,
        governance_decisions=(),
        executions=(
            ExecutionLatencySample(
                requested_at=_dt(0),
                completed_at=_dt(0) + timedelta(milliseconds=10),
                failed_at=None,
                state="completed",
            ),
        ),
        qa_scores=(),
        escalation_count=0,
        dlq_count=0,
    )
    assert small.execution_latency_ms_p99 is None

    samples = tuple(
        ExecutionLatencySample(
            requested_at=_dt(0),
            completed_at=_dt(0) + timedelta(milliseconds=index),
            failed_at=None,
            state="completed",
        )
        for index in range(1, 101)
    )
    full = build_metrics_snapshot(
        tenant_id="tenant-acme",
        window_start=_dt(0),
        window_end=_dt(60),
        ticket_throughput=0,
        governance_decisions=(),
        executions=samples,
        qa_scores=(),
        escalation_count=0,
        dlq_count=0,
    )

    assert full.execution_latency_ms_p99 == 99.0


@pytest.mark.asyncio
async def test_alert_thresholds_evaluate_against_metric_snapshot() -> None:
    runtime = _runtime()
    await runtime.define_slo(
        tenant_id="tenant-acme",
        metric_name=OperationalMetricName.GOVERNANCE_DENY_RATE,
        threshold_operator=AlertThresholdOperator.GREATER_THAN_OR_EQUAL,
        threshold_value=0.4,
        window_minutes=60,
        severity=AlertSeverity.WARNING,
        now=_dt(0),
    )
    await runtime.define_slo(
        tenant_id="tenant-acme",
        metric_name=OperationalMetricName.TICKET_THROUGHPUT,
        threshold_operator=AlertThresholdOperator.LESS_THAN,
        threshold_value=1.0,
        window_minutes=60,
        severity=AlertSeverity.CRITICAL,
        now=_dt(0),
    )
    await runtime.define_slo(
        tenant_id="tenant-acme",
        metric_name=OperationalMetricName.DLQ_COUNT,
        threshold_operator=AlertThresholdOperator.GREATER_THAN,
        threshold_value=0.0,
        window_minutes=60,
        severity=AlertSeverity.INFO,
        enabled=False,
        now=_dt(0),
    )

    first = await runtime.evaluate_alerts(
        query=OperationalMetricsQuery(window_start=_dt(0), window_end=_dt(60)),
        expected_tenant_id="tenant-acme",
    )
    second = await runtime.evaluate_alerts(
        query=OperationalMetricsQuery(window_start=_dt(0), window_end=_dt(60)),
        expected_tenant_id="tenant-acme",
    )

    assert first == second
    assert first.total == 2
    triggered = {item.metric_name: item.triggered for item in first.items}
    assert triggered[OperationalMetricName.GOVERNANCE_DENY_RATE] is True
    assert triggered[OperationalMetricName.TICKET_THROUGHPUT] is False


@pytest.mark.asyncio
async def test_structured_trace_spans_are_deterministic_and_tenant_scoped() -> None:
    runtime = _runtime()

    first = await runtime.record_trace_span(
        tenant_id="tenant-acme",
        trace_id="trace-1",
        span_name="metrics.read",
        substrate="observability",
        operation="read_metrics",
        started_at=_dt(1),
        ended_at=_dt(1) + timedelta(milliseconds=25),
        status=OperationalTraceStatus.OK,
        attributes={"source": "unit"},
    )
    duplicate = await runtime.record_trace_span(
        tenant_id="tenant-acme",
        trace_id="trace-1",
        span_name="metrics.read",
        substrate="observability",
        operation="read_metrics",
        started_at=_dt(1),
        ended_at=_dt(1) + timedelta(milliseconds=25),
        status=OperationalTraceStatus.OK,
        attributes={"source": "unit"},
    )
    own = await runtime.list_trace_spans(
        query=OperationalTraceSpanQuery(trace_id="trace-1"),
        expected_tenant_id="tenant-acme",
    )
    other = await runtime.list_trace_spans(
        query=OperationalTraceSpanQuery(trace_id="trace-1"),
        expected_tenant_id="tenant-other",
    )

    assert duplicate.span_id == first.span_id
    assert first.latency_ms == 25.0
    assert own.total == 1
    assert other.total == 0
    with pytest.raises(ValueError):
        await runtime.record_trace_span(
            tenant_id="tenant-acme",
            trace_id="trace-2",
            span_name="bad",
            substrate="observability",
            operation="bad",
            started_at=_dt(2),
            ended_at=_dt(1),
            status=OperationalTraceStatus.FAILED,
        )


def _runtime() -> OperationalObservabilityRuntime:
    persistence = InMemoryOperationalObservabilityPersistence(
        boundary_ingress_records=(
            _ingress(1, tenant_id="tenant-acme"),
            _ingress(2, tenant_id="tenant-acme"),
            _ingress(3, tenant_id="tenant-other"),
        ),
        governance_decision_records=(
            _decision(1, tenant_id="tenant-acme", decision="allow"),
            _decision(2, tenant_id="tenant-acme", decision="deny"),
            _decision(3, tenant_id="tenant-other", decision="deny"),
        ),
        execution_records=(
            _execution(
                1,
                tenant_id="tenant-acme",
                state=ExecutionState.COMPLETED,
                completed_at=_dt(10) + timedelta(milliseconds=500),
            ),
            _execution(
                2,
                tenant_id="tenant-acme",
                state=ExecutionState.DEAD_LETTERED,
                failed_at=_dt(11) + timedelta(milliseconds=1000),
            ),
            _execution(
                3,
                tenant_id="tenant-other",
                state=ExecutionState.COMPLETED,
                completed_at=_dt(12) + timedelta(milliseconds=200),
            ),
        ),
        qa_score_records=(
            _qa_score(1, tenant_id="tenant-acme", overall_score=0.9),
            _qa_score(2, tenant_id="tenant-acme", overall_score=0.4),
            _qa_score(3, tenant_id="tenant-other", overall_score=0.2),
        ),
        escalation_records=(
            _escalation(1, tenant_id="tenant-acme"),
            _escalation(2, tenant_id="tenant-other"),
        ),
    )
    return OperationalObservabilityRuntime(persistence=persistence)


def _ingress(index: int, *, tenant_id: str) -> BoundaryIngressRecord:
    event_id = BoundaryEventId(_uuid(200 + index))
    return BoundaryIngressRecord(
        ingress_id=BoundaryIngressId(_uuid(100 + index)),
        direction=BoundaryDirection.INGRESS,
        runtime_instance_id=_uuid(900),
        sequence=index,
        source_type=BoundarySourceType.EMAIL,
        source_id=f"source-{index}",
        tenant_id=tenant_id,
        adapter_name="email",
        normalization_status=BoundaryNormalizationStatus.OK,
        message_type=BoundaryMessageType.MESSAGE_RECEIVED,
        replay_disposition=BoundaryReplayDisposition.NEW,
        replay_key=_uuid(300 + index),
        event_id=event_id,
        original_event_id=None,
        external_message_id=f"msg-{index}",
        external_conversation_id=f"conv-{index}",
        external_emitted_at=_dt(index),
        received_at=_dt(index),
        started_at=_dt(index),
        ended_at=_dt(index) + timedelta(milliseconds=1),
        latency_ms=1.0,
        correlation_id=f"corr-{index}",
        request_id=f"req-{index}",
        canonical_payload={"subject": "hi"},
        error=None,
    )


def _decision(
    index: int,
    *,
    tenant_id: str,
    decision: str,
) -> GovernanceDecisionRecord:
    return GovernanceDecisionRecord(
        decision_id=str(_uuid(400 + index)),
        decision=decision,
        stage="pre_execution",
        policy_chain_id="chain",
        reason=decision,
        decided_at=_dt(5 + index).isoformat(),
        tenant_id=tenant_id,
    )


def _execution(
    index: int,
    *,
    tenant_id: str,
    state: ExecutionState,
    completed_at: datetime | None = None,
    failed_at: datetime | None = None,
) -> ExecutionRecord:
    return ExecutionRecord(
        execution_id=ExecutionId(_uuid(600 + index)),
        kind=ExecutionKind.DIAGNOSTIC_AGENT,
        dispatch_id=f"dispatch-{index}",
        session_id=f"00000000-0000-0000-0000-000000007{index:03d}",
        tenant_id=tenant_id,
        state=state,
        attempt_count=1,
        requested_at=_dt(9 + index),
        completed_at=completed_at,
        failed_at=failed_at,
        worker_id=f"worker-{index}",
        error="boom" if state is ExecutionState.DEAD_LETTERED else None,
    )


def _qa_score(
    index: int,
    *,
    tenant_id: str,
    overall_score: float,
) -> QAScoreRecord:
    return QAScoreRecord(
        score_id=str(_uuid(700 + index)),
        inspection_id=str(_uuid(710 + index)),
        execution_id=str(_uuid(600 + index)),
        tenant_id=tenant_id,
        tenant_authority_source="request",
        diagnostic_accuracy=overall_score,
        policy_compliance=overall_score,
        timeline_integrity=overall_score,
        resolution_quality=overall_score,
        overall_score=overall_score,
        supervisor_decision_kind="accept",
        finding_count=0,
        evaluation_count=1,
        escalation_count=0,
        scored_at=_dt(20 + index).isoformat(),
    )


def _escalation(index: int, *, tenant_id: str) -> EscalationRecord:
    return EscalationRecord(
        escalation_id=str(_uuid(800 + index)),
        session_id=str(_uuid(810 + index)),
        tenant_id=tenant_id,
        reason="deny",
        governance_decision_id=str(_uuid(400 + index)),
        status="pending",
        created_at=_dt(30 + index).isoformat(),
    )


def _uuid(value: int) -> uuid.UUID:
    return uuid.UUID(f"00000000-0000-0000-0000-{value:012d}")
