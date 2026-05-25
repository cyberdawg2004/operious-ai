"""dead-letter task replay columns

Revision ID: 0039_dlq_replay_cols
Revises: 0038_provider_quota
Create Date: 2026-05-25
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0039_dlq_replay_cols"
down_revision: Union[str, None] = "0038_provider_quota"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "dead_letter_tasks",
        sa.Column("queue", sa.Text(), nullable=True),
    )
    op.add_column(
        "dead_letter_tasks",
        sa.Column(
            "replayed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "dead_letter_tasks",
        sa.Column("replayed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "dead_letter_tasks",
        sa.Column("replayed_by", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_dead_letter_tasks_replayed",
        "dead_letter_tasks",
        ["replayed", "tenant_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_dead_letter_tasks_replayed", table_name="dead_letter_tasks")
    op.drop_column("dead_letter_tasks", "replayed_by")
    op.drop_column("dead_letter_tasks", "replayed_at")
    op.drop_column("dead_letter_tasks", "replayed")
    op.drop_column("dead_letter_tasks", "queue")
