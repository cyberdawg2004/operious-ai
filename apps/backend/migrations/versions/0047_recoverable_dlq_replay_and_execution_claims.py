"""recoverable DLQ replay and execution outbox claim tokens

Revision ID: 0047_recoverable_dlq_replay_and_execution_claims
Revises: 0046_boundary_egress_governance_decision
Create Date: 2026-05-29
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0047_recoverable_dlq_replay_and_execution_claims"
down_revision: Union[str, None] = "0046_boundary_egress_governance_decision"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "execution_outbox",
        sa.Column("claim_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        op.f("ix_execution_outbox_claim_id"),
        "execution_outbox",
        ["claim_id"],
    )

    op.add_column(
        "dead_letter_tasks",
        sa.Column(
            "replay_state",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'none'"),
        ),
    )
    op.add_column(
        "dead_letter_tasks",
        sa.Column("replay_claim_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "dead_letter_tasks",
        sa.Column(
            "replay_attempt_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "dead_letter_tasks",
        sa.Column("replay_claimed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "dead_letter_tasks",
        sa.Column("replay_last_error", sa.Text(), nullable=True),
    )
    op.execute(
        "UPDATE dead_letter_tasks "
        "SET replay_state = CASE WHEN replayed THEN 'published' ELSE 'none' END"
    )
    op.create_check_constraint(
        "dead_letter_replay_state_valid",
        "dead_letter_tasks",
        "replay_state IN ('none', 'claimed', 'published', 'failed')",
    )
    op.create_check_constraint(
        "dead_letter_replay_attempt_nonnegative",
        "dead_letter_tasks",
        "replay_attempt_count >= 0",
    )
    op.create_index(
        op.f("ix_dead_letter_tasks_replay_state"),
        "dead_letter_tasks",
        ["replay_state"],
    )
    op.create_index(
        op.f("ix_dead_letter_tasks_replay_claim_id"),
        "dead_letter_tasks",
        ["replay_claim_id"],
    )
    op.create_index(
        op.f("ix_dead_letter_tasks_replay_claimed_at"),
        "dead_letter_tasks",
        ["replay_claimed_at"],
    )
    op.create_index(
        "ix_dead_letter_tasks_replay_state_tenant",
        "dead_letter_tasks",
        ["replay_state", "tenant_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_dead_letter_tasks_replay_state_tenant",
        table_name="dead_letter_tasks",
    )
    op.drop_index(
        op.f("ix_dead_letter_tasks_replay_claimed_at"),
        table_name="dead_letter_tasks",
    )
    op.drop_index(
        op.f("ix_dead_letter_tasks_replay_claim_id"),
        table_name="dead_letter_tasks",
    )
    op.drop_index(
        op.f("ix_dead_letter_tasks_replay_state"),
        table_name="dead_letter_tasks",
    )
    op.drop_constraint(
        "dead_letter_replay_attempt_nonnegative",
        "dead_letter_tasks",
        type_="check",
    )
    op.drop_constraint(
        "dead_letter_replay_state_valid",
        "dead_letter_tasks",
        type_="check",
    )
    op.drop_column("dead_letter_tasks", "replay_last_error")
    op.drop_column("dead_letter_tasks", "replay_claimed_at")
    op.drop_column("dead_letter_tasks", "replay_attempt_count")
    op.drop_column("dead_letter_tasks", "replay_claim_id")
    op.drop_column("dead_letter_tasks", "replay_state")

    op.drop_index(
        op.f("ix_execution_outbox_claim_id"),
        table_name="execution_outbox",
    )
    op.drop_column("execution_outbox", "claim_id")
