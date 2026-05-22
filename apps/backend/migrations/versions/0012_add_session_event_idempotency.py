"""add session event idempotency keys (Phase 1-D)

Revision ID: 0012_session_event_idempotency
Revises: 0011_execution
Create Date: 2026-05-21 00:00:00.000000

The session timeline remains the canonical chronology authority.
This column gives that authority a replay-stable dedupe key for
execution/attempt projections without moving chronology control into
workers or transport.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0012_session_event_idempotency"
down_revision: Union[str, None] = "0011_execution"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "session_events",
        sa.Column(
            "idempotency_key",
            sa.String(length=255),
            nullable=True,
        ),
    )
    op.create_index(
        op.f("ix_session_events_idempotency_key"),
        "session_events",
        ["idempotency_key"],
    )
    op.create_unique_constraint(
        "uq_session_events_session_id_idempotency_key",
        "session_events",
        ["session_id", "idempotency_key"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_session_events_session_id_idempotency_key",
        "session_events",
        type_="unique",
    )
    op.drop_index(
        op.f("ix_session_events_idempotency_key"),
        table_name="session_events",
    )
    op.drop_column("session_events", "idempotency_key")
