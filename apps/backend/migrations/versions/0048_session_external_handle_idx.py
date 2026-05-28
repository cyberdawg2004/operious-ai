"""add session tenant external handle continuity index

Revision ID: 0048_session_external_handle_idx
Revises: 0047_recoverable_dlq_replay_and_execution_claims
Create Date: 2026-05-29 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0048_session_external_handle_idx"
down_revision: Union[str, None] = "0047_recoverable_dlq_replay_and_execution_claims"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS
                ix_sessions_tenant_external_handle
            ON operational_sessions (tenant_id, external_handle)
            WHERE external_handle IS NOT NULL
            """
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            """
            DROP INDEX CONCURRENTLY IF EXISTS
                ix_sessions_tenant_external_handle
            """
        )
