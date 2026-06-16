"""Add tenant_knowledge_uploads table and ingestion-status columns.

Revision ID: 0086_knowledge_uploads_and_ingestion_status
Revises: 0085_outbound_send_outbox_reconciliation
Create Date: 2026-06-16

Changes (all additive / zero-downtime):
  - tenant_knowledge_documents: add updated_at (timestamptz, server_default now()),
    last_index_error (text, nullable)
  - tenant_knowledge_uploads: new table with RLS + FORCE RLS + tenant_isolation policy
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0086_knowledge_uploads_and_ingestion_status"
down_revision: str = "0085_outbound_send_outbox_reconciliation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. New columns on tenant_knowledge_documents (nullable / default only) ──
    op.add_column(
        "tenant_knowledge_documents",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.add_column(
        "tenant_knowledge_documents",
        sa.Column("last_index_error", sa.Text, nullable=True),
    )

    # ── 2. New table: tenant_knowledge_uploads ────────────────────────────────
    op.create_table(
        "tenant_knowledge_uploads",
        sa.Column(
            "upload_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            sa.String(255),
            sa.ForeignKey("tenants.tenant_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "document_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "tenant_knowledge_documents.document_id", ondelete="SET NULL"
            ),
            nullable=True,
        ),
        sa.Column("filename", sa.String(510), nullable=False),
        sa.Column("content_type", sa.String(64), nullable=False),
        sa.Column("byte_size", sa.Integer, nullable=False),
        sa.Column("raw_content", sa.LargeBinary, nullable=False),
        sa.Column("uploaded_by", sa.String(255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("length(tenant_id) > 0", name="tenant_id_nonempty"),
        sa.CheckConstraint(
            "byte_size >= 0", name="knowledge_upload_byte_size_nonnegative"
        ),
    )
    op.create_index(
        "ix_tenant_knowledge_uploads_tenant_id",
        "tenant_knowledge_uploads",
        ["tenant_id"],
    )
    op.create_index(
        "ix_tenant_knowledge_uploads_tenant_document",
        "tenant_knowledge_uploads",
        ["tenant_id", "document_id"],
    )

    # ── 3. RLS ────────────────────────────────────────────────────────────────
    op.execute(
        "ALTER TABLE public.tenant_knowledge_uploads ENABLE ROW LEVEL SECURITY"
    )
    op.execute(
        "ALTER TABLE public.tenant_knowledge_uploads FORCE ROW LEVEL SECURITY"
    )
    op.execute(
        """
        CREATE POLICY tenant_isolation ON public.tenant_knowledge_uploads
        USING (
            tenant_id = current_setting('app.current_tenant_id', true)
        )
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS tenant_isolation ON public.tenant_knowledge_uploads"
    )
    op.drop_table("tenant_knowledge_uploads")
    op.drop_column("tenant_knowledge_documents", "last_index_error")
    op.drop_column("tenant_knowledge_documents", "updated_at")
