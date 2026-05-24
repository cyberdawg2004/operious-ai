"""Postgres tests for Phase 6-A operational observability persistence."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.observability.enums import (
    AlertSeverity,
    AlertThresholdOperator,
    OperationalMetricName,
    OperationalTraceStatus,
)
from app.observability.persistence import (
    OperationalMetricsQuery,
    OperationalTraceSpanQuery,
    PostgresOperationalObservabilityPersistence,
)
from app.observability.runtime import OperationalObservabilityRuntime
from tests.conftest import requires_postgres

pytestmark = [requires_postgres]

_NOW = datetime(2026, 5, 22, 9, tzinfo=timezone.utc)


@pytest.fixture
def pg_tenant_id() -> str:
    return "tenant-acme"


@pytest.mark.asyncio
async def test_slo_and_trace_span_records_are_tenant_scoped(
    pg_session: AsyncSession,
) -> None:
    runtime = OperationalObservabilityRuntime(
        persistence=PostgresOperationalObservabilityPersistence(pg_session)
    )

    slo = await runtime.define_slo(
        tenant_id="tenant-acme",
        metric_name=OperationalMetricName.EXECUTION_LATENCY_MS_P95,
        threshold_operator=AlertThresholdOperator.LESS_THAN_OR_EQUAL,
        threshold_value=5000,
        window_minutes=60,
        severity=AlertSeverity.WARNING,
        now=_NOW,
    )
    own_slo = await runtime.get_slo_definition(
        slo_id=slo.slo_id,
        expected_tenant_id="tenant-acme",
    )
    other_slo = await runtime.get_slo_definition(
        slo_id=slo.slo_id,
        expected_tenant_id="tenant-other",
    )

    span = await runtime.record_trace_span(
        tenant_id="tenant-acme",
        trace_id="trace-pg",
        span_name="observability.persist",
        substrate="observability",
        operation="record_trace_span",
        started_at=_NOW,
        ended_at=_NOW + timedelta(milliseconds=12),
        status=OperationalTraceStatus.OK,
        created_at=_NOW,
    )
    duplicate = await runtime.record_trace_span(
        tenant_id="tenant-acme",
        trace_id="trace-pg",
        span_name="observability.persist",
        substrate="observability",
        operation="record_trace_span",
        started_at=_NOW,
        ended_at=_NOW + timedelta(milliseconds=12),
        status=OperationalTraceStatus.OK,
        created_at=_NOW,
    )
    own_traces = await runtime.list_trace_spans(
        query=OperationalTraceSpanQuery(trace_id="trace-pg"),
        expected_tenant_id="tenant-acme",
    )
    other_traces = await runtime.list_trace_spans(
        query=OperationalTraceSpanQuery(trace_id="trace-pg"),
        expected_tenant_id="tenant-other",
    )

    assert own_slo == slo
    assert other_slo is None
    assert duplicate.span_id == span.span_id
    assert own_traces.total == 1
    assert other_traces.total == 0


@pytest.mark.asyncio
async def test_empty_postgres_metric_snapshot_is_deterministic(
    pg_session: AsyncSession,
) -> None:
    runtime = OperationalObservabilityRuntime(
        persistence=PostgresOperationalObservabilityPersistence(pg_session)
    )
    query = OperationalMetricsQuery(
        window_start=_NOW,
        window_end=_NOW + timedelta(hours=1),
    )

    first = await runtime.read_metrics(
        query=query,
        expected_tenant_id="tenant-empty",
    )
    second = await runtime.read_metrics(
        query=query,
        expected_tenant_id="tenant-empty",
    )

    assert first == second
    assert first.ticket_throughput == 0
    assert first.governance_deny_rate == 0.0
    assert first.execution_latency_ms_p95 is None
    assert first.qa_score_distribution[-1].count == 0
