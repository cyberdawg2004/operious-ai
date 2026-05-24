"""escalation outbox claim token

Revision ID: 0032_escalation_outbox_claim_id
Revises: 0031_dead_letter_tasks
Create Date: 2026-05-24 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0032_escalation_outbox_claim_id"
down_revision: Union[str, None] = "0031_dead_letter_tasks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "escalation_outbox",
        sa.Column("claim_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        op.f("ix_escalation_outbox_claim_id"),
        "escalation_outbox",
        ["claim_id"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_escalation_outbox_claim_id"),
        table_name="escalation_outbox",
    )
    op.drop_column("escalation_outbox", "claim_id")
