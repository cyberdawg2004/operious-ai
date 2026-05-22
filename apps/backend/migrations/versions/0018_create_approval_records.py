"""create approval records table (Phase 3-D)

Revision ID: 0018_approval_records
Revises: 0017_escalation_records
Create Date: 2026-05-22 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0018_approval_records"
down_revision: Union[str, None] = "0017_escalation_records"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "approval_records",
        sa.Column("approval_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("proposed_change", sa.Text(), nullable=False),
        sa.Column(
            "evidence_sessions",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("proposed_by", sa.String(length=255), nullable=False),
        sa.Column("reviewed_by", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.CheckConstraint(
            "length(tenant_id) > 0",
            name=op.f("ck_approval_records_tenant_id_nonempty"),
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name=op.f("ck_approval_records_confidence_bounds"),
        ),
        sa.CheckConstraint(
            "status IN ('pending_review', 'approved', 'rejected', 'applied')",
            name=op.f("ck_approval_records_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["tenant_knowledge_documents.document_id"],
            name=op.f(
                "fk_approval_records_document_id_tenant_knowledge_documents"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.tenant_id"],
            name=op.f("fk_approval_records_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "approval_id", name=op.f("pk_approval_records")
        ),
    )
    for col in (
        "tenant_id",
        "document_id",
        "status",
        "reviewed_by",
        "created_at",
    ):
        op.create_index(
            op.f(f"ix_approval_records_{col}"),
            "approval_records",
            [col],
        )
    op.create_index(
        "ix_approval_records_tenant_status",
        "approval_records",
        ["tenant_id", "status"],
    )
    op.create_index(
        "ix_approval_records_tenant_created",
        "approval_records",
        ["tenant_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("approval_records")
