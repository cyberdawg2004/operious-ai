"""webhook nonce records (Phase F)

Revision ID: 0028_webhook_nonce_records
Revises: 0027_provider_circuit_states
Create Date: 2026-05-23 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0028_webhook_nonce_records"
down_revision: Union[str, None] = "0027_provider_circuit_states"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "webhook_nonce_records",
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("channel_type", sa.String(length=64), nullable=False),
        sa.Column("nonce", sa.String(length=1020), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(tenant_id) > 0",
            name=op.f("ck_webhook_nonce_records_tenant_id_nonempty"),
        ),
        sa.CheckConstraint(
            "length(channel_type) > 0",
            name=op.f("ck_webhook_nonce_records_channel_type_nonempty"),
        ),
        sa.CheckConstraint(
            "length(nonce) > 0",
            name=op.f("ck_webhook_nonce_records_nonce_nonempty"),
        ),
        sa.CheckConstraint(
            "expires_at > received_at",
            name=op.f("ck_webhook_nonce_records_expires_after_received"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.tenant_id"],
            name=op.f("fk_webhook_nonce_records_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "tenant_id",
            "channel_type",
            "nonce",
            name=op.f("pk_webhook_nonce_records"),
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "channel_type",
            "nonce",
            name="uq_webhook_nonce_records_tenant_channel_nonce",
        ),
    )
    op.create_index(
        op.f("ix_webhook_nonce_records_tenant_id"),
        "webhook_nonce_records",
        ["tenant_id"],
    )
    op.create_index(
        op.f("ix_webhook_nonce_records_received_at"),
        "webhook_nonce_records",
        ["received_at"],
    )
    op.create_index(
        op.f("ix_webhook_nonce_records_expires_at"),
        "webhook_nonce_records",
        ["expires_at"],
    )
    op.create_index(
        "ix_webhook_nonce_records_tenant_channel",
        "webhook_nonce_records",
        ["tenant_id", "channel_type"],
    )
    op.execute("ALTER TABLE webhook_nonce_records ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON webhook_nonce_records
        USING (operious_tenant_rls_allows(tenant_id))
        WITH CHECK (operious_tenant_rls_allows(tenant_id))
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON webhook_nonce_records")
    op.drop_table("webhook_nonce_records")
