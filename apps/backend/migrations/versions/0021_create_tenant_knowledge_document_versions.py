"""create tenant knowledge document version history (Phase 5-B)

Revision ID: 0021_tenant_knowledge_versions
Revises: 0020_tenant_knowledge_vectors
Create Date: 2026-05-22 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0021_tenant_knowledge_versions"
down_revision: Union[str, None] = "0020_tenant_knowledge_vectors"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tenant_knowledge_document_versions",
        sa.Column("version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=510), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("document_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("uploaded_by", sa.String(length=255), nullable=False),
        sa.Column("source_approval_id", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(tenant_id) > 0",
            name=op.f("ck_tenant_knowledge_document_versions_tenant_id_nonempty"),
        ),
        sa.CheckConstraint(
            "version >= 1",
            name=op.f("ck_tenant_knowledge_document_versions_version_positive"),
        ),
        sa.CheckConstraint(
            "status IN ('active', 'archived', 'pending_index', 'indexing')",
            name="ck_tenant_knowledge_document_versions_status_valid",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.tenant_id"],
            name=op.f("fk_tenant_knowledge_document_versions_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["tenant_knowledge_documents.document_id"],
            name="fk_tenant_knowledge_document_versions_document",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "version_id",
            name=op.f("pk_tenant_knowledge_document_versions"),
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "document_id",
            "version",
            name="uq_tenant_knowledge_document_versions_tenant_doc_version",
        ),
    )
    for col in (
        "tenant_id",
        "document_id",
        "document_type",
        "status",
        "source_approval_id",
    ):
        op.create_index(
            op.f(f"ix_tenant_knowledge_document_versions_{col}"),
            "tenant_knowledge_document_versions",
            [col],
        )
    op.create_index(
        "ix_tenant_knowledge_document_versions_tenant_document",
        "tenant_knowledge_document_versions",
        ["tenant_id", "document_id"],
    )
    op.create_index(
        "ix_tenant_knowledge_document_versions_tenant_status",
        "tenant_knowledge_document_versions",
        ["tenant_id", "status"],
    )


def downgrade() -> None:
    op.drop_table("tenant_knowledge_document_versions")
