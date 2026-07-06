"""Backfill proposed_by sentinel for action_approval_records where still NULL.

Revision ID: 0103_backfill_action_approval_proposed_by_sentinel
Revises: 0102_mcp_server_change_types
Create Date: 2026-07-06

Security fix F6: rows that were created before migration 0093 and did not have
an agent_action_actor metadata key still have proposed_by=NULL. The service-layer
dual-control guard (approver≠proposer) skips the check when proposed_by IS NULL,
leaving a window where someone could self-approve a pre-migration pending action.

This migration backfills remaining NULLs with the sentinel string
"pre-migration-unknown". After this runs, the service guard's `is not None`
bypass will be removed so ALL records are subject to the approver≠proposer check.
The sentinel is deliberately not a valid principal ID (no auth system produces it)
so it cannot be spoofed by any real approver identity.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0103_backfill_action_approval_proposed_by_sentinel"
down_revision: Union[str, None] = "0102_mcp_server_change_types"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SENTINEL = "pre-migration-unknown"


def upgrade() -> None:
    op.execute(
        f"""
        UPDATE public.action_approval_records
        SET proposed_by = '{_SENTINEL}'
        WHERE proposed_by IS NULL
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        UPDATE public.action_approval_records
        SET proposed_by = NULL
        WHERE proposed_by = '{_SENTINEL}'
        """
    )
