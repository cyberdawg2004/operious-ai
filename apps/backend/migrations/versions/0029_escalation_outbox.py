"""escalation outbox (Phase G)

Revision ID: 0029_escalation_outbox
Revises: 0028_webhook_nonce_records
Create Date: 2026-05-23 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0029_escalation_outbox"
down_revision: Union[str, None] = "0028_webhook_nonce_records"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "escalation_outbox",
        sa.Column("outbox_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("escalation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("publisher_id", sa.String(length=255), nullable=True),
        sa.Column("republish_count", sa.Integer(), nullable=False),
        sa.Column("dead_letter", sa.Boolean(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(tenant_id) > 0",
            name=op.f("ck_escalation_outbox_tenant_id_nonempty"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'publishing', 'published', 'failed')",
            name="ck_escalation_outbox_status_valid",
        ),
        sa.CheckConstraint(
            "republish_count >= 0",
            name=op.f("ck_escalation_outbox_republish_count_nonnegative"),
        ),
        sa.ForeignKeyConstraint(
            ["escalation_id"],
            ["escalation_records.escalation_id"],
            name=op.f("fk_escalation_outbox_escalation_id_escalation_records"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.tenant_id"],
            name=op.f("fk_escalation_outbox_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "outbox_id",
            name=op.f("pk_escalation_outbox"),
        ),
        sa.UniqueConstraint(
            "escalation_id",
            name="uq_escalation_outbox_escalation_id",
        ),
    )
    op.create_index(
        op.f("ix_escalation_outbox_escalation_id"),
        "escalation_outbox",
        ["escalation_id"],
    )
    op.create_index(
        op.f("ix_escalation_outbox_tenant_id"),
        "escalation_outbox",
        ["tenant_id"],
    )
    op.create_index(
        op.f("ix_escalation_outbox_status"),
        "escalation_outbox",
        ["status"],
    )
    op.create_index(
        op.f("ix_escalation_outbox_created_at"),
        "escalation_outbox",
        ["created_at"],
    )
    op.create_index(
        op.f("ix_escalation_outbox_claimed_at"),
        "escalation_outbox",
        ["claimed_at"],
    )
    op.create_index(
        op.f("ix_escalation_outbox_published_at"),
        "escalation_outbox",
        ["published_at"],
    )
    op.create_index(
        op.f("ix_escalation_outbox_publisher_id"),
        "escalation_outbox",
        ["publisher_id"],
    )
    op.create_index(
        "ix_escalation_outbox_tenant_status",
        "escalation_outbox",
        ["tenant_id", "status"],
    )
    op.execute("ALTER TABLE escalation_outbox ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON escalation_outbox
        USING (operious_tenant_rls_allows(tenant_id))
        WITH CHECK (operious_tenant_rls_allows(tenant_id))
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON escalation_outbox")
    op.drop_table("escalation_outbox")
