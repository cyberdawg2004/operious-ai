"""widen alembic version column

Revision ID: 0033_widen_alembic_version
Revises: 0032_escalation_outbox_claim_id
Create Date: 2026-05-25 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0033_widen_alembic_version"
down_revision: Union[str, None] = "0032_escalation_outbox_claim_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE alembic_version "
        "ALTER COLUMN version_num TYPE varchar(128)"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE alembic_version "
        "ALTER COLUMN version_num TYPE varchar(32)"
    )
