"""admission_records table.

Revision ID: 0036_admission_records
Revises: 0035_tenant_not_null
Create Date: 2026-05-25
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0036_admission_records"
down_revision = "0035_tenant_not_null"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "admission_records",
        sa.Column(
            "decision_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("tenant_id", sa.String(length=255), nullable=True),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.String(length=64), nullable=True),
        sa.Column("queue_name", sa.String(length=128), nullable=False),
        sa.Column("queue_depth", sa.Integer(), nullable=False),
        sa.Column("queue_age_seconds", sa.Float(), nullable=True),
        sa.Column("redis_memory_pct", sa.Float(), nullable=True),
        sa.Column("db_pool_wait_ms", sa.Float(), nullable=True),
        sa.Column(
            "retry_after_seconds",
            sa.Integer(),
            nullable=False,
            server_default="30",
        ),
        sa.Column("channel", sa.String(length=64), nullable=True),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_admission_records_tenant_id",
        "admission_records",
        ["tenant_id"],
    )
    op.create_index(
        "ix_admission_records_tenant_evaluated",
        "admission_records",
        ["tenant_id", "evaluated_at"],
    )
    op.create_index(
        "ix_admission_records_outcome",
        "admission_records",
        ["outcome"],
    )
    # Intentionally no RLS: this is an operational capacity log with no
    # tenant-facing read API in PR_T3.


def downgrade() -> None:
    op.drop_index(
        "ix_admission_records_outcome",
        table_name="admission_records",
    )
    op.drop_index(
        "ix_admission_records_tenant_evaluated",
        table_name="admission_records",
    )
    op.drop_index(
        "ix_admission_records_tenant_id",
        table_name="admission_records",
    )
    op.drop_table("admission_records")
