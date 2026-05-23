"""dead-letter task records (Phase H)

Revision ID: 0031_dead_letter_tasks
Revises: 0030_cognition_audit_records
Create Date: 2026-05-23 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0031_dead_letter_tasks"
down_revision: Union[str, None] = "0030_cognition_audit_records"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dead_letter_tasks",
        sa.Column(
            "dead_letter_task_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("task_name", sa.String(length=255), nullable=False),
        sa.Column("task_id", sa.String(length=255), nullable=False),
        sa.Column("execution_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
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
            name=op.f("ck_dead_letter_tasks_tenant_id_nonempty"),
        ),
        sa.CheckConstraint(
            "length(task_name) > 0",
            name=op.f("ck_dead_letter_tasks_task_name_nonempty"),
        ),
        sa.CheckConstraint(
            "length(task_id) > 0",
            name=op.f("ck_dead_letter_tasks_task_id_nonempty"),
        ),
        sa.CheckConstraint(
            "length(reason) > 0",
            name=op.f("ck_dead_letter_tasks_reason_nonempty"),
        ),
        sa.CheckConstraint(
            "retry_count >= 0",
            name=op.f("ck_dead_letter_tasks_dead_letter_retry_nonnegative"),
        ),
        sa.ForeignKeyConstraint(
            ["execution_id"],
            ["execution_records.execution_id"],
            name="fk_dead_letter_tasks_execution_id_execution_records",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.tenant_id"],
            name=op.f("fk_dead_letter_tasks_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "dead_letter_task_id",
            name=op.f("pk_dead_letter_tasks"),
        ),
        sa.UniqueConstraint(
            "task_name",
            "task_id",
            name="uq_dead_letter_tasks_task_name_task_id",
        ),
    )
    op.create_index(
        op.f("ix_dead_letter_tasks_tenant_id"),
        "dead_letter_tasks",
        ["tenant_id"],
    )
    op.create_index(
        op.f("ix_dead_letter_tasks_task_name"),
        "dead_letter_tasks",
        ["task_name"],
    )
    op.create_index(
        op.f("ix_dead_letter_tasks_task_id"),
        "dead_letter_tasks",
        ["task_id"],
    )
    op.create_index(
        op.f("ix_dead_letter_tasks_execution_id"),
        "dead_letter_tasks",
        ["execution_id"],
    )
    op.create_index(
        "ix_dead_letter_tasks_tenant_created",
        "dead_letter_tasks",
        ["tenant_id", "created_at"],
    )
    op.execute("ALTER TABLE dead_letter_tasks ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON dead_letter_tasks
        USING (operious_tenant_rls_allows(tenant_id))
        WITH CHECK (operious_tenant_rls_allows(tenant_id))
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON dead_letter_tasks")
    op.drop_table("dead_letter_tasks")
