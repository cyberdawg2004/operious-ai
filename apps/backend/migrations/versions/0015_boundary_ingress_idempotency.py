"""add durable boundary ingress idempotency

Revision ID: 0015_boundary_idempotency
Revises: 0014_tenant_config
Create Date: 2026-05-22 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0015_boundary_idempotency"
down_revision: Union[str, None] = "0014_tenant_config"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        WITH ranked AS (
            SELECT
                ingress_id,
                row_number() OVER (
                    PARTITION BY replay_key
                    ORDER BY
                        received_at,
                        runtime_instance_id,
                        sequence,
                        ingress_id
                ) AS row_rank
            FROM boundary_ingress
            WHERE replay_key IS NOT NULL
        )
        DELETE FROM boundary_ingress AS ingress
        USING ranked
        WHERE ingress.ingress_id = ranked.ingress_id
          AND ranked.row_rank > 1
        """
    )
    op.execute(
        """
        WITH ranked AS (
            SELECT
                ingress_id,
                row_number() OVER (
                    PARTITION BY event_id
                    ORDER BY
                        received_at,
                        runtime_instance_id,
                        sequence,
                        ingress_id
                ) AS row_rank
            FROM boundary_ingress
            WHERE event_id IS NOT NULL
        )
        DELETE FROM boundary_ingress AS ingress
        USING ranked
        WHERE ingress.ingress_id = ranked.ingress_id
          AND ranked.row_rank > 1
        """
    )
    op.create_index(
        "uq_boundary_ingress_replay_key",
        "boundary_ingress",
        ["replay_key"],
        unique=True,
        postgresql_where=sa.text("replay_key IS NOT NULL"),
    )
    op.create_index(
        "uq_boundary_ingress_event_id",
        "boundary_ingress",
        ["event_id"],
        unique=True,
        postgresql_where=sa.text("event_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_boundary_ingress_event_id",
        table_name="boundary_ingress",
        postgresql_where=sa.text("event_id IS NOT NULL"),
    )
    op.drop_index(
        "uq_boundary_ingress_replay_key",
        table_name="boundary_ingress",
        postgresql_where=sa.text("replay_key IS NOT NULL"),
    )
