"""tenant channel self-service metadata

Revision ID: 0084_tenant_channel_self_service_metadata
Revises: 0083_outbound_send_outbox
Create Date: 2026-06-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0084_tenant_channel_self_service_metadata"
down_revision: str | None = "0083_outbound_send_outbox"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "tenant_channel_configurations"


def upgrade() -> None:
    op.add_column(
        _TABLE,
        sa.Column(
            "self_service_config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        schema="public",
    )
    op.add_column(
        _TABLE,
        sa.Column("last_validation_error", sa.Text(), nullable=True),
        schema="public",
    )
    op.add_column(
        _TABLE,
        sa.Column(
            "validation_evidence",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        schema="public",
    )


def downgrade() -> None:
    op.drop_column(_TABLE, "validation_evidence", schema="public")
    op.drop_column(_TABLE, "last_validation_error", schema="public")
    op.drop_column(_TABLE, "self_service_config", schema="public")
