"""operational observability surfaces (Phase 6-A)

Revision ID: 0023_operational_observability
Revises: 0022_cognition_llm_usage
Create Date: 2026-05-22 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0023_operational_observability"
down_revision: Union[str, None] = "0022_cognition_llm_usage"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "operational_slo_definitions",
        sa.Column("slo_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("metric_name", sa.String(length=64), nullable=False),
        sa.Column("threshold_operator", sa.String(length=64), nullable=False),
        sa.Column("threshold_value", sa.Float(), nullable=False),
        sa.Column("window_minutes", sa.Integer(), nullable=False),
        sa.Column("severity", sa.String(length=64), nullable=False),
        sa.Column(
            "enabled",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(tenant_id) > 0",
            name=op.f("ck_operational_slo_definitions_tenant_id_nonempty"),
        ),
        sa.CheckConstraint(
            "window_minutes >= 1",
            name=op.f(
                "ck_operational_slo_definitions_slo_window_minutes_positive"
            ),
        ),
        sa.CheckConstraint(
            "threshold_operator IN ("
            "'greater_than', 'greater_than_or_equal', "
            "'less_than', 'less_than_or_equal')",
            name=op.f(
                "ck_operational_slo_definitions_slo_threshold_operator_valid"
            ),
        ),
        sa.CheckConstraint(
            "severity IN ('info', 'warning', 'critical')",
            name=op.f("ck_operational_slo_definitions_slo_severity_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.tenant_id"],
            name=op.f("fk_operational_slo_definitions_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "slo_id",
            name=op.f("pk_operational_slo_definitions"),
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "metric_name",
            "window_minutes",
            "severity",
            name="uq_operational_slo_definitions_tenant_metric_window_severity",
        ),
    )
    op.create_index(
        op.f("ix_operational_slo_definitions_tenant_id"),
        "operational_slo_definitions",
        ["tenant_id"],
    )
    op.create_index(
        op.f("ix_operational_slo_definitions_metric_name"),
        "operational_slo_definitions",
        ["metric_name"],
    )
    op.create_index(
        op.f("ix_operational_slo_definitions_severity"),
        "operational_slo_definitions",
        ["severity"],
    )
    op.create_index(
        "ix_operational_slo_definitions_tenant_enabled",
        "operational_slo_definitions",
        ["tenant_id", "enabled"],
    )

    op.create_table(
        "operational_trace_spans",
        sa.Column("span_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("trace_id", sa.String(length=255), nullable=False),
        sa.Column("parent_span_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("span_name", sa.String(length=255), nullable=False),
        sa.Column("substrate", sa.String(length=64), nullable=False),
        sa.Column("operation", sa.String(length=255), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("latency_ms", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "attributes",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(tenant_id) > 0",
            name=op.f("ck_operational_trace_spans_tenant_id_nonempty"),
        ),
        sa.CheckConstraint(
            "length(trace_id) > 0",
            name=op.f("ck_operational_trace_spans_trace_id_nonempty"),
        ),
        sa.CheckConstraint(
            "length(span_name) > 0",
            name=op.f("ck_operational_trace_spans_span_name_nonempty"),
        ),
        sa.CheckConstraint(
            "length(substrate) > 0",
            name=op.f("ck_operational_trace_spans_substrate_nonempty"),
        ),
        sa.CheckConstraint(
            "length(operation) > 0",
            name=op.f("ck_operational_trace_spans_operation_nonempty"),
        ),
        sa.CheckConstraint(
            "ended_at >= started_at",
            name=op.f("ck_operational_trace_spans_span_time_order"),
        ),
        sa.CheckConstraint(
            "latency_ms >= 0",
            name=op.f("ck_operational_trace_spans_span_latency_nonnegative"),
        ),
        sa.CheckConstraint(
            "status IN ('ok', 'failed')",
            name=op.f("ck_operational_trace_spans_span_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["parent_span_id"],
            ["operational_trace_spans.span_id"],
            name=op.f(
                "fk_operational_trace_spans_parent_span_id_operational_trace_spans"
            ),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.tenant_id"],
            name=op.f("fk_operational_trace_spans_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "span_id",
            name=op.f("pk_operational_trace_spans"),
        ),
    )
    op.create_index(
        op.f("ix_operational_trace_spans_tenant_id"),
        "operational_trace_spans",
        ["tenant_id"],
    )
    op.create_index(
        op.f("ix_operational_trace_spans_trace_id"),
        "operational_trace_spans",
        ["trace_id"],
    )
    op.create_index(
        op.f("ix_operational_trace_spans_parent_span_id"),
        "operational_trace_spans",
        ["parent_span_id"],
    )
    op.create_index(
        op.f("ix_operational_trace_spans_substrate"),
        "operational_trace_spans",
        ["substrate"],
    )
    op.create_index(
        op.f("ix_operational_trace_spans_started_at"),
        "operational_trace_spans",
        ["started_at"],
    )
    op.create_index(
        op.f("ix_operational_trace_spans_status"),
        "operational_trace_spans",
        ["status"],
    )
    op.create_index(
        "ix_operational_trace_spans_tenant_trace_started",
        "operational_trace_spans",
        ["tenant_id", "trace_id", "started_at"],
    )


def downgrade() -> None:
    op.drop_table("operational_trace_spans")
    op.drop_table("operational_slo_definitions")
