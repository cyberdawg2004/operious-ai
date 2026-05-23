"""create workflow + task execution tables

Revision ID: 0002_orchestration
Revises: 0001_initial
Create Date: 2026-05-13 23:23:55.658934

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_orchestration"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "workflow_executions",
        sa.Column("workflow_name", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("latency_ms", sa.Float(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("output", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.String(length=255), nullable=True),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workflow_executions")),
    )
    op.create_index(
        op.f("ix_workflow_executions_request_id"),
        "workflow_executions",
        ["request_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_workflow_executions_started_at"),
        "workflow_executions",
        ["started_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_workflow_executions_status"),
        "workflow_executions",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_workflow_executions_workflow_name"),
        "workflow_executions",
        ["workflow_name"],
        unique=False,
    )

    op.create_table(
        "task_executions",
        sa.Column("workflow_execution_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_name", sa.String(length=128), nullable=False),
        sa.Column("sequence_index", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("latency_ms", sa.Float(), nullable=True),
        sa.Column("input_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("output", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.String(length=255), nullable=True),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["workflow_execution_id"],
            ["workflow_executions.id"],
            name=op.f(
                "fk_task_executions_workflow_execution_id_workflow_executions"
            ),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_task_executions")),
    )
    op.create_index(
        op.f("ix_task_executions_status"),
        "task_executions",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_task_executions_task_name"),
        "task_executions",
        ["task_name"],
        unique=False,
    )
    op.create_index(
        op.f("ix_task_executions_workflow_execution_id"),
        "task_executions",
        ["workflow_execution_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_task_executions_workflow_execution_id"),
        table_name="task_executions",
    )
    op.drop_index(op.f("ix_task_executions_task_name"), table_name="task_executions")
    op.drop_index(op.f("ix_task_executions_status"), table_name="task_executions")
    op.drop_table("task_executions")

    op.drop_index(
        op.f("ix_workflow_executions_workflow_name"),
        table_name="workflow_executions",
    )
    op.drop_index(
        op.f("ix_workflow_executions_status"),
        table_name="workflow_executions",
    )
    op.drop_index(
        op.f("ix_workflow_executions_started_at"),
        table_name="workflow_executions",
    )
    op.drop_index(
        op.f("ix_workflow_executions_request_id"),
        table_name="workflow_executions",
    )
    op.drop_table("workflow_executions")
