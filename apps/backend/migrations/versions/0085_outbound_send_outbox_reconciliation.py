"""outbound send outbox: send_attempted_at + needs_reconciliation status

Revision ID: 0085_outbound_send_outbox_reconciliation
Revises: 0084_tenant_channel_self_service_metadata
Create Date: 2026-06-15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0085_outbound_send_outbox_reconciliation"
down_revision: str | None = "0084_tenant_channel_self_service_metadata"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "outbound_send_outbox"
_STATUS_CONSTRAINT = "ck_outbound_send_outbox_status_valid"


def upgrade() -> None:
    op.add_column(
        _TABLE,
        sa.Column("send_attempted_at", sa.DateTime(timezone=True), nullable=True),
        schema="public",
    )
    op.drop_constraint(
        op.f(_STATUS_CONSTRAINT),
        _TABLE,
        schema="public",
        type_="check",
    )
    op.create_check_constraint(
        op.f(_STATUS_CONSTRAINT),
        _TABLE,
        "status IN ('pending', 'claimed', 'sent', 'dead_lettered', 'needs_reconciliation')",
        schema="public",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f(_STATUS_CONSTRAINT),
        _TABLE,
        schema="public",
        type_="check",
    )
    op.create_check_constraint(
        op.f(_STATUS_CONSTRAINT),
        _TABLE,
        "status IN ('pending', 'claimed', 'sent', 'dead_lettered')",
        schema="public",
    )
    op.drop_column(_TABLE, "send_attempted_at", schema="public")
