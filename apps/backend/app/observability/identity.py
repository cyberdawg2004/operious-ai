"""Deterministic identities for operational observability records."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import NewType

from app.identity import coerce_tenant_id
from app.observability.enums import AlertSeverity, OperationalMetricName


OperationalSLODefinitionId = NewType("OperationalSLODefinitionId", uuid.UUID)
OperationalTraceSpanId = NewType("OperationalTraceSpanId", uuid.UUID)
OperationalAlertId = NewType("OperationalAlertId", uuid.UUID)

_SLO_DEFINITION_NAMESPACE = uuid.UUID("6a0b5001-0001-4001-8001-000000000001")
_TRACE_SPAN_NAMESPACE = uuid.UUID("6a0b5001-0002-4002-8002-000000000002")
_ALERT_NAMESPACE = uuid.UUID("6a0b5001-0003-4003-8003-000000000003")


def derive_slo_definition_id(
    *,
    tenant_id: str,
    metric_name: OperationalMetricName,
    window_minutes: int,
    severity: AlertSeverity,
) -> OperationalSLODefinitionId:
    """Derive the stable identity of one tenant SLO threshold."""

    tenant = coerce_tenant_id(tenant_id)
    if window_minutes < 1:
        raise ValueError("window_minutes must be >= 1")
    seed = f"{tenant}|{metric_name.value}|{window_minutes}|{severity.value}"
    return OperationalSLODefinitionId(
        uuid.uuid5(_SLO_DEFINITION_NAMESPACE, seed)
    )


def derive_trace_span_id(
    *,
    tenant_id: str,
    trace_id: str,
    span_name: str,
    operation: str,
    started_at: datetime,
    parent_span_id: uuid.UUID | str | None = None,
) -> OperationalTraceSpanId:
    """Derive the stable identity of one structured trace span."""

    tenant = coerce_tenant_id(tenant_id)
    trace = _require_text(trace_id, "trace_id")
    name = _require_text(span_name, "span_name")
    op = _require_text(operation, "operation")
    parent = "" if parent_span_id is None else str(parent_span_id)
    seed = f"{tenant}|{trace}|{parent}|{name}|{op}|{started_at.isoformat()}"
    return OperationalTraceSpanId(uuid.uuid5(_TRACE_SPAN_NAMESPACE, seed))


def derive_alert_id(
    *,
    tenant_id: str,
    slo_id: uuid.UUID | str,
    window_start: datetime,
    window_end: datetime,
) -> OperationalAlertId:
    """Derive a deterministic identity for one threshold evaluation."""

    tenant = coerce_tenant_id(tenant_id)
    seed = (
        f"{tenant}|{slo_id}|"
        f"{window_start.isoformat()}|{window_end.isoformat()}"
    )
    return OperationalAlertId(uuid.uuid5(_ALERT_NAMESPACE, seed))


def as_operational_slo_id(
    value: uuid.UUID | str,
) -> OperationalSLODefinitionId:
    return OperationalSLODefinitionId(
        value if isinstance(value, uuid.UUID) else uuid.UUID(value)
    )


def as_operational_trace_span_id(
    value: uuid.UUID | str,
) -> OperationalTraceSpanId:
    return OperationalTraceSpanId(
        value if isinstance(value, uuid.UUID) else uuid.UUID(value)
    )


def _require_text(value: str, field_name: str) -> str:
    text = value.strip()
    if not text:
        raise ValueError(f"{field_name} must be non-empty")
    return text


__all__ = [
    "OperationalAlertId",
    "OperationalSLODefinitionId",
    "OperationalTraceSpanId",
    "as_operational_slo_id",
    "as_operational_trace_span_id",
    "derive_alert_id",
    "derive_slo_definition_id",
    "derive_trace_span_id",
]
