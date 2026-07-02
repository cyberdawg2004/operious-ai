"""Add proposed_by column to action_approval_records for dual-control enforcement.

Revision ID: 0093_action_approval_proposed_by
Revises: 0092_resolution_verdict_template_purpose_rename
Create Date: 2026-07-03

Dual-control doctrine gap (security audit finding B): the action-approval
path lacked a first-class proposer identity column, making it impossible
to enforce approver≠proposer at the service layer. This migration adds
the column and backfills existing rows from the stored metadata JSON
(agent_action_actor key), which is where the proposer identity has been
stored since the table was created.

The column is nullable: rows created before this migration that had no
agent_action_actor in metadata receive NULL. The service guard skips the
separation check when proposed_by IS NULL, so old records remain
approvable. New records always carry proposed_by.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0093_action_approval_proposed_by"
down_revision: Union[str, None] = "0092_resolution_verdict_template_purpose_rename"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "action_approval_records",
        sa.Column("proposed_by", sa.String(length=255), nullable=True),
        schema="public",
    )
    # Backfill from metadata JSON where the agent_action_actor key is present.
    op.execute(
        """
        UPDATE public.action_approval_records
        SET proposed_by = metadata->>'agent_action_actor'
        WHERE metadata->>'agent_action_actor' IS NOT NULL
          AND proposed_by IS NULL
        """
    )


def downgrade() -> None:
    op.drop_column("action_approval_records", "proposed_by", schema="public")
