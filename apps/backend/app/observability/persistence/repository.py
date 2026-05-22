"""Operational observability persistence protocol."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.observability.identity import (
    OperationalSLODefinitionId,
    OperationalTraceSpanId,
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
    OperationalMetricsSnapshotRecord,
    OperationalSLODefinitionRecord,
    OperationalTraceSpanRecord,
)


@runtime_checkable
class OperationalObservabilityPersistence(Protocol):
    """Tenant-scoped read/config contract for operational observability."""

    async def read_metrics(
        self,
        query: OperationalMetricsQuery,
        *,
        expected_tenant_id: str,
    ) -> OperationalMetricsSnapshotRecord: ...

    async def list_dead_letter_executions(
        self,
        query: DeadLetterExecutionQuery,
        *,
        expected_tenant_id: str,
    ) -> DeadLetterExecutionPage: ...

    async def save_slo_definition(
        self,
        record: OperationalSLODefinitionRecord,
        *,
        expected_tenant_id: str,
    ) -> OperationalSLODefinitionRecord: ...

    async def get_slo_definition(
        self,
        slo_id: OperationalSLODefinitionId,
        *,
        expected_tenant_id: str,
    ) -> OperationalSLODefinitionRecord | None: ...

    async def list_slo_definitions(
        self,
        query: OperationalSLODefinitionQuery,
        *,
        expected_tenant_id: str,
    ) -> OperationalSLODefinitionPage: ...

    async def save_trace_span(
        self,
        record: OperationalTraceSpanRecord,
        *,
        expected_tenant_id: str,
    ) -> OperationalTraceSpanRecord: ...

    async def get_trace_span(
        self,
        span_id: OperationalTraceSpanId,
        *,
        expected_tenant_id: str,
    ) -> OperationalTraceSpanRecord | None: ...

    async def list_trace_spans(
        self,
        query: OperationalTraceSpanQuery,
        *,
        expected_tenant_id: str,
    ) -> OperationalTraceSpanPage: ...


__all__ = ["OperationalObservabilityPersistence"]
