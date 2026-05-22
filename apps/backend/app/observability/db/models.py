"""Operational observability ORM rows."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TENANT_ID_MAX_LENGTH

_ENUM_WIDTH = 64
_HANDLE_WIDTH = 255


class OperationalSLODefinitionRow(Base):
    """Tenant-owned SLO definition and alert threshold."""

    __tablename__ = "operational_slo_definitions"

    slo_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(TENANT_ID_MAX_LENGTH),
        ForeignKey("tenants.tenant_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    metric_name: Mapped[str] = mapped_column(
        String(_ENUM_WIDTH), nullable=False, index=True
    )
    threshold_operator: Mapped[str] = mapped_column(
        String(_ENUM_WIDTH), nullable=False
    )
    threshold_value: Mapped[float] = mapped_column(Float, nullable=False)
    window_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    severity: Mapped[str] = mapped_column(
        String(_ENUM_WIDTH), nullable=False, index=True
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )

    __table_args__ = (
        CheckConstraint("length(tenant_id) > 0", name="tenant_id_nonempty"),
        CheckConstraint("window_minutes >= 1", name="slo_window_minutes_positive"),
        CheckConstraint(
            "threshold_operator IN ("
            "'greater_than', 'greater_than_or_equal', "
            "'less_than', 'less_than_or_equal')",
            name="slo_threshold_operator_valid",
        ),
        CheckConstraint(
            "severity IN ('info', 'warning', 'critical')",
            name="slo_severity_valid",
        ),
        UniqueConstraint(
            "tenant_id",
            "metric_name",
            "window_minutes",
            "severity",
            name="uq_operational_slo_definitions_tenant_metric_window_severity",
        ),
        Index(
            "ix_operational_slo_definitions_tenant_enabled",
            "tenant_id",
            "enabled",
        ),
    )


class OperationalTraceSpanRow(Base):
    """Durable structured trace span independent of Sentry."""

    __tablename__ = "operational_trace_spans"

    span_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(TENANT_ID_MAX_LENGTH),
        ForeignKey("tenants.tenant_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    trace_id: Mapped[str] = mapped_column(
        String(_HANDLE_WIDTH), nullable=False, index=True
    )
    parent_span_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("operational_trace_spans.span_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    span_name: Mapped[str] = mapped_column(String(_HANDLE_WIDTH), nullable=False)
    substrate: Mapped[str] = mapped_column(
        String(_ENUM_WIDTH), nullable=False, index=True
    )
    operation: Mapped[str] = mapped_column(String(_HANDLE_WIDTH), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    ended_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    latency_ms: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(
        String(_ENUM_WIDTH), nullable=False, index=True
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attributes: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("length(tenant_id) > 0", name="tenant_id_nonempty"),
        CheckConstraint("length(trace_id) > 0", name="trace_id_nonempty"),
        CheckConstraint("length(span_name) > 0", name="span_name_nonempty"),
        CheckConstraint("length(substrate) > 0", name="substrate_nonempty"),
        CheckConstraint("length(operation) > 0", name="operation_nonempty"),
        CheckConstraint("ended_at >= started_at", name="span_time_order"),
        CheckConstraint("latency_ms >= 0", name="span_latency_nonnegative"),
        CheckConstraint(
            "status IN ('ok', 'failed')",
            name="span_status_valid",
        ),
        Index(
            "ix_operational_trace_spans_tenant_trace_started",
            "tenant_id",
            "trace_id",
            "started_at",
        ),
    )


__all__ = [
    "OperationalSLODefinitionRow",
    "OperationalTraceSpanRow",
]
