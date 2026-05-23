"""execution governance hardening surfaces (Phase 6-B)

Revision ID: 0024_execution_governance
Revises: 0023_operational_observability
Create Date: 2026-05-22 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0024_execution_governance"
down_revision: Union[str, None] = "0023_operational_observability"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tenant_execution_governance_configurations",
        sa.Column("config_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("execution_quota", sa.Integer(), nullable=False),
        sa.Column("throughput_limit", sa.Integer(), nullable=False),
        sa.Column("throughput_window_minutes", sa.Integer(), nullable=False),
        sa.Column("governance_budget_limit", sa.Integer(), nullable=False),
        sa.Column(
            "governance_budget_window_minutes",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column("circuit_failure_threshold", sa.Integer(), nullable=False),
        sa.Column("circuit_window_minutes", sa.Integer(), nullable=False),
        sa.Column("circuit_cooldown_minutes", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("configured_by", sa.String(length=255), nullable=False),
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
            name=op.f(
                "ck_tenant_execution_governance_configurations_tenant_id_nonempty"
            ),
        ),
        sa.CheckConstraint(
            "status IN ('active', 'draft', 'archived')",
            name=op.f(
                "ck_tenant_execution_governance_configurations_execution_governance_status_valid"
            ),
        ),
        sa.CheckConstraint(
            "execution_quota >= 1",
            name=op.f(
                "ck_tenant_execution_governance_configurations_execution_quota_positive"
            ),
        ),
        sa.CheckConstraint(
            "throughput_limit >= 1",
            name=op.f(
                "ck_tenant_execution_governance_configurations_throughput_limit_positive"
            ),
        ),
        sa.CheckConstraint(
            "throughput_window_minutes >= 1",
            name=op.f(
                "ck_tenant_execution_governance_configurations_throughput_window_minutes_positive"
            ),
        ),
        sa.CheckConstraint(
            "governance_budget_limit >= 1",
            name=op.f(
                "ck_tenant_execution_governance_configurations_governance_budget_limit_positive"
            ),
        ),
        sa.CheckConstraint(
            "governance_budget_window_minutes >= 1",
            name=op.f(
                "ck_tenant_execution_governance_configurations_governance_budget_window_minutes_positive"
            ),
        ),
        sa.CheckConstraint(
            "circuit_failure_threshold >= 1",
            name=op.f(
                "ck_tenant_execution_governance_configurations_circuit_failure_threshold_positive"
            ),
        ),
        sa.CheckConstraint(
            "circuit_window_minutes >= 1",
            name=op.f(
                "ck_tenant_execution_governance_configurations_circuit_window_minutes_positive"
            ),
        ),
        sa.CheckConstraint(
            "circuit_cooldown_minutes >= 1",
            name=op.f(
                "ck_tenant_execution_governance_configurations_circuit_cooldown_minutes_positive"
            ),
        ),
        sa.CheckConstraint(
            "version >= 1",
            name=op.f(
                "ck_tenant_execution_governance_configurations_version_positive"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.tenant_id"],
            name=op.f(
                "fk_tenant_execution_governance_configurations_tenant_id_tenants"
            ),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "config_id",
            name=op.f("pk_tenant_execution_governance_configurations"),
        ),
        sa.UniqueConstraint(
            "tenant_id",
            name="uq_tenant_execution_governance_configurations_tenant",
        ),
    )
    op.create_index(
        op.f("ix_tenant_execution_governance_configurations_tenant_id"),
        "tenant_execution_governance_configurations",
        ["tenant_id"],
    )
    op.create_index(
        op.f("ix_tenant_execution_governance_configurations_status"),
        "tenant_execution_governance_configurations",
        ["status"],
    )
    op.create_index(
        "ix_tenant_execution_governance_configurations_tenant_status",
        "tenant_execution_governance_configurations",
        ["tenant_id", "status"],
    )

    op.create_table(
        "tenant_execution_circuit_breakers",
        sa.Column("breaker_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("config_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("state", sa.String(length=64), nullable=False),
        sa.Column("failure_count", sa.Integer(), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("open_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "last_transition_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("reason", sa.Text(), nullable=True),
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
            name=op.f("ck_tenant_execution_circuit_breakers_tenant_id_nonempty"),
        ),
        sa.CheckConstraint(
            "state IN ('closed', 'open', 'half_open')",
            name=op.f(
                "ck_tenant_execution_circuit_breakers_execution_circuit_state_valid"
            ),
        ),
        sa.CheckConstraint(
            "failure_count >= 0",
            name=op.f(
                "ck_tenant_execution_circuit_breakers_failure_count_nonnegative"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["config_id"],
            ["tenant_execution_governance_configurations.config_id"],
            name=op.f(
                "fk_tenant_execution_circuit_breakers_config_id_tenant_execution_governance_configurations"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.tenant_id"],
            name=op.f("fk_tenant_execution_circuit_breakers_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "breaker_id",
            name=op.f("pk_tenant_execution_circuit_breakers"),
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "config_id",
            name="uq_tenant_execution_circuit_breakers_tenant_config",
        ),
    )
    op.create_index(
        op.f("ix_tenant_execution_circuit_breakers_tenant_id"),
        "tenant_execution_circuit_breakers",
        ["tenant_id"],
    )
    op.create_index(
        op.f("ix_tenant_execution_circuit_breakers_config_id"),
        "tenant_execution_circuit_breakers",
        ["config_id"],
    )
    op.create_index(
        op.f("ix_tenant_execution_circuit_breakers_state"),
        "tenant_execution_circuit_breakers",
        ["state"],
    )
    op.create_index(
        "ix_tenant_execution_circuit_breakers_tenant_state",
        "tenant_execution_circuit_breakers",
        ["tenant_id", "state"],
    )


def downgrade() -> None:
    op.drop_table("tenant_execution_circuit_breakers")
    op.drop_table("tenant_execution_governance_configurations")
