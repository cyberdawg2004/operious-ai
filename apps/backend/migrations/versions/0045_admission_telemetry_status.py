"""add telemetry status to admission records

Revision ID: 0045_admission_telemetry_status
Revises: 0044_resolution_drafts
Create Date: 2026-05-28
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0045_admission_telemetry_status"
down_revision: Union[str, None] = "0044_resolution_drafts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "admission_records",
        sa.Column("channel_class", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "admission_records",
        sa.Column(
            "queue_depth_available",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
    )
    op.add_column(
        "admission_records",
        sa.Column(
            "queue_age_available",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
    )
    op.add_column(
        "admission_records",
        sa.Column(
            "redis_memory_available",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
    )
    op.add_column(
        "admission_records",
        sa.Column(
            "telemetry_unavailable",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    op.add_column(
        "admission_records",
        sa.Column("unavailable_reasons", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("admission_records", "unavailable_reasons")
    op.drop_column("admission_records", "telemetry_unavailable")
    op.drop_column("admission_records", "redis_memory_available")
    op.drop_column("admission_records", "queue_age_available")
    op.drop_column("admission_records", "queue_depth_available")
    op.drop_column("admission_records", "channel_class")
