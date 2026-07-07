"""Add connector_credentials table for per-connector OPCRED2 credential storage.

Revision ID: 0100_connector_credentials_table
Revises: 0099_knowledge_contradiction_metadata
Create Date: 2026-07-06

Introduces ``connector_credentials`` — a dedicated per-connector encrypted
credential store that is decoupled from the channel-level
``tenant_channel_configurations`` table.

Motivation: non-commerce tenants (banking, telecom, etc.) configure custom
connectors that are not backed by a TenantChannelType enum entry. They need
their own credential envelope separate from the OMS/WhatsApp/Email channel
credential paths, while reusing the same OPCRED2 AES-256-GCM envelope format.

Schema:
  - (tenant_id, connector_id) primary key — one active credential per connector.
  - credentials_enc: OPCRED2 binary envelope — never returned in API responses.
  - credential_hash: SHA-256 hex of credentials_enc — stored in change-request
    sentinels for integrity verification between propose and apply.
  - status: 'pending_validation' | 'active' | 'disabled'
  - configured_by, source_approval_id: audit trail.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0100_connector_credentials_table"
down_revision: Union[str, None] = "0099_knowledge_contradiction_metadata"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "connector_credentials",
        sa.Column(
            "tenant_id",
            sa.String(255),
            sa.ForeignKey("tenants.tenant_id", ondelete="RESTRICT"),
            nullable=False,
            primary_key=True,
        ),
        sa.Column(
            "connector_id",
            sa.String(255),
            nullable=False,
            primary_key=True,
            comment="Matches the connector_id segment in ConnectorDefinition.",
        ),
        sa.Column(
            "credentials_enc",
            sa.LargeBinary(),
            nullable=False,
            comment="OPCRED2 AES-256-GCM encrypted credential JSON.",
        ),
        sa.Column(
            "credential_hash",
            sa.String(64),
            nullable=False,
            comment="SHA-256 hex of credentials_enc for change-request sentinel integrity.",
        ),
        sa.Column(
            "status",
            sa.String(64),
            nullable=False,
            server_default="pending_validation",
        ),
        sa.Column("configured_by", sa.String(255), nullable=False),
        sa.Column(
            "source_approval_id",
            sa.String(255),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("length(tenant_id) > 0", name="cc_tenant_id_nonempty"),
        sa.CheckConstraint("length(connector_id) > 0", name="cc_connector_id_nonempty"),
        sa.CheckConstraint(
            "status IN ('pending_validation', 'active', 'disabled')",
            name="cc_status_valid",
        ),
        sa.CheckConstraint("length(configured_by) > 0", name="cc_configured_by_nonempty"),
        sa.CheckConstraint(
            "length(source_approval_id) > 0",
            name="cc_source_approval_id_nonempty",
        ),
        sa.CheckConstraint("length(credential_hash) = 64", name="cc_credential_hash_len"),
    )
    op.create_index(
        "ix_connector_credentials_tenant_status",
        "connector_credentials",
        ["tenant_id", "status"],
    )
    op.create_index(
        "ix_connector_credentials_source_approval",
        "connector_credentials",
        ["source_approval_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_connector_credentials_source_approval", "connector_credentials")
    op.drop_index("ix_connector_credentials_tenant_status", "connector_credentials")
    op.drop_table("connector_credentials")
