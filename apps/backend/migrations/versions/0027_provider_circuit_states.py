"""provider circuit breaker states (Phase D)

Revision ID: 0027_provider_circuit_states
Revises: 0026_chronology_append_only
Create Date: 2026-05-23 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0027_provider_circuit_states"
down_revision: Union[str, None] = "0026_chronology_append_only"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "provider_circuit_states",
        sa.Column("state_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("provider_name", sa.String(length=255), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("retry_window_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("open_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "half_open_trial_started_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("last_failure_reason", sa.String(length=255), nullable=True),
        sa.Column("last_transition_at", sa.DateTime(timezone=True), nullable=False),
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
            name=op.f("ck_provider_circuit_states_tenant_id_nonempty"),
        ),
        sa.CheckConstraint(
            "length(provider_name) > 0",
            name=op.f("ck_provider_circuit_states_provider_name_nonempty"),
        ),
        sa.CheckConstraint(
            "state IN ('closed', 'open', 'half_open')",
            name="ck_provider_circuit_states_provider_circuit_state_valid",
        ),
        sa.CheckConstraint(
            "consecutive_failures >= 0",
            name=op.f(
                "ck_provider_circuit_states_consecutive_failures_nonnegative"
            ),
        ),
        sa.CheckConstraint(
            "retry_count >= 0",
            name=op.f("ck_provider_circuit_states_retry_count_nonnegative"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.tenant_id"],
            name=op.f("fk_provider_circuit_states_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "state_id",
            name=op.f("pk_provider_circuit_states"),
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "provider_name",
            name="uq_provider_circuit_states_tenant_provider",
        ),
    )
    op.create_index(
        op.f("ix_provider_circuit_states_tenant_id"),
        "provider_circuit_states",
        ["tenant_id"],
    )
    op.create_index(
        op.f("ix_provider_circuit_states_provider_name"),
        "provider_circuit_states",
        ["provider_name"],
    )
    op.create_index(
        op.f("ix_provider_circuit_states_state"),
        "provider_circuit_states",
        ["state"],
    )
    op.create_index(
        "ix_provider_circuit_states_tenant_state",
        "provider_circuit_states",
        ["tenant_id", "state"],
    )


def downgrade() -> None:
    op.drop_table("provider_circuit_states")
