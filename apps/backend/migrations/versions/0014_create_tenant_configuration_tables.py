"""create tenant-owned configuration tables (Phase 2.5-A)

Revision ID: 0014_tenant_config
Revises: 0013_operational_events
Create Date: 2026-05-22 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014_tenant_config"
down_revision: Union[str, None] = "0013_operational_events"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(tenant_id) > 0",
            name=op.f("ck_tenants_tenant_id_nonempty"),
        ),
        sa.PrimaryKeyConstraint("tenant_id", name=op.f("pk_tenants")),
    )

    op.create_table(
        "tenant_channel_configurations",
        sa.Column(
            "config_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("channel_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column(
            "routing_address", sa.String(length=1020), nullable=False
        ),
        sa.Column("credentials_enc", sa.LargeBinary(), nullable=False),
        sa.Column("webhook_secret", sa.Text(), nullable=False),
        sa.Column(
            "verified_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(tenant_id) > 0",
            name=op.f(
                "ck_tenant_channel_configurations_tenant_id_nonempty"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.tenant_id"],
            name=op.f(
                "fk_tenant_channel_configurations_tenant_id_tenants"
            ),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "config_id",
            name=op.f("pk_tenant_channel_configurations"),
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "channel_type",
            name="uq_tenant_channel_configurations_tenant_channel",
        ),
    )
    for col in ("tenant_id", "channel_type", "status"):
        op.create_index(
            op.f(f"ix_tenant_channel_configurations_{col}"),
            "tenant_channel_configurations",
            [col],
        )
    op.create_index(
        "ix_tenant_channel_configurations_tenant_status",
        "tenant_channel_configurations",
        ["tenant_id", "status"],
    )

    op.create_table(
        "tenant_knowledge_documents",
        sa.Column(
            "document_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("title", sa.String(length=510), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("document_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("uploaded_by", sa.String(length=255), nullable=False),
        sa.Column(
            "vector_indexed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(tenant_id) > 0",
            name=op.f("ck_tenant_knowledge_documents_tenant_id_nonempty"),
        ),
        sa.CheckConstraint(
            "version >= 1",
            name=op.f("ck_tenant_knowledge_documents_version_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.tenant_id"],
            name=op.f("fk_tenant_knowledge_documents_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "document_id", name=op.f("pk_tenant_knowledge_documents")
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "document_type",
            "title",
            name="uq_tenant_knowledge_documents_tenant_type_title",
        ),
    )
    for col in ("tenant_id", "document_type", "status"):
        op.create_index(
            op.f(f"ix_tenant_knowledge_documents_{col}"),
            "tenant_knowledge_documents",
            [col],
        )
    op.create_index(
        "ix_tenant_knowledge_documents_tenant_status",
        "tenant_knowledge_documents",
        ["tenant_id", "status"],
    )

    op.create_table(
        "tenant_governance_policies",
        sa.Column(
            "policy_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("policy_type", sa.String(length=255), nullable=False),
        sa.Column(
            "parameters",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("approved_by", sa.String(length=255), nullable=False),
        sa.Column(
            "effective_from", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(tenant_id) > 0",
            name=op.f("ck_tenant_governance_policies_tenant_id_nonempty"),
        ),
        sa.CheckConstraint(
            "version >= 1",
            name=op.f("ck_tenant_governance_policies_version_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.tenant_id"],
            name=op.f("fk_tenant_governance_policies_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "policy_id", name=op.f("pk_tenant_governance_policies")
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "policy_type",
            name="uq_tenant_governance_policies_tenant_type",
        ),
    )
    for col in ("tenant_id", "policy_type", "status"):
        op.create_index(
            op.f(f"ix_tenant_governance_policies_{col}"),
            "tenant_governance_policies",
            [col],
        )
    op.create_index(
        "ix_tenant_governance_policies_tenant_status",
        "tenant_governance_policies",
        ["tenant_id", "status"],
    )


def downgrade() -> None:
    op.drop_table("tenant_governance_policies")
    op.drop_table("tenant_knowledge_documents")
    op.drop_table("tenant_channel_configurations")
    op.drop_table("tenants")
