"""add knowledge document review status trust gate

Revision ID: 0065_knowledge_review_status
Revises: 0064_agent_action_grants
Create Date: 2026-06-01
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0065_knowledge_review_status"
down_revision: Union[str, None] = "0064_agent_action_grants"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tenant_knowledge_documents",
        sa.Column(
            "review_status",
            sa.String(length=64),
            server_default=sa.text("'quarantined'"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "knowledge_document_review_status_valid",
        "tenant_knowledge_documents",
        "review_status IN ('quarantined', 'approved', 'rejected')",
    )
    op.create_index(
        "ix_tenant_knowledge_documents_tenant_review_status",
        "tenant_knowledge_documents",
        ["tenant_id", "review_status"],
    )
    op.execute(
        """
        -- WHY: active documents that already existed before the S-07
        -- quarantine control were loaded by the operator and are
        -- grandfathered as operator-trusted. All documents created after
        -- this migration keep the default 'quarantined' review_status and
        -- must earn 'approved' before retrieval can expose them to LLMs.
        UPDATE tenant_knowledge_documents
        SET review_status = 'approved'
        WHERE status = 'active'
        """
    )
    op.execute(
        """
        COMMENT ON COLUMN tenant_knowledge_documents.review_status IS
        'Trust gate for knowledge retrieval. Migration 0065 backfilled pre-existing active documents to approved as operator-trusted; new documents default to quarantined.'
        """
    )


def downgrade() -> None:
    op.drop_index(
        "ix_tenant_knowledge_documents_tenant_review_status",
        table_name="tenant_knowledge_documents",
    )
    op.drop_constraint(
        "knowledge_document_review_status_valid",
        "tenant_knowledge_documents",
        type_="check",
    )
    op.drop_column("tenant_knowledge_documents", "review_status")
