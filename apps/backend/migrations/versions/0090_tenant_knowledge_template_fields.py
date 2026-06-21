"""tenant_knowledge_documents template fields (Phase W0)

Revision ID: 0090_tenant_knowledge_template_fields
Revises: 0089_whatsapp_media_fetch_records
Create Date: 2026-06-21

Adds the two structured columns a TEMPLATE-typed knowledge document needs
for exact-match retrieval by a downstream workflow (a future probe-dispatch
step looks up "the template for this tenant, this purpose, this channel" —
not a semantic/vector search, so it cannot reuse the chunking/embedding
path SOP/POLICY documents use). No new table: this is the same
tenant_knowledge_documents store, same RLS, same QUARANTINED->APPROVED
review gate, same dual-control creation path — just two more nullable
columns, populated only when document_type='template'.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0090_tenant_knowledge_template_fields"
down_revision: Union[str, None] = "0089_whatsapp_media_fetch_records"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "tenant_knowledge_documents"


def upgrade() -> None:
    op.add_column(
        _TABLE,
        sa.Column("template_purpose", sa.String(length=255), nullable=True),
    )
    op.add_column(
        _TABLE,
        sa.Column("template_channel", sa.String(length=64), nullable=True),
    )
    op.create_check_constraint(
        op.f("ck_tenant_knowledge_documents_template_fields_match_type"),
        _TABLE,
        "(document_type = 'template' AND template_purpose IS NOT NULL "
        "AND template_channel IS NOT NULL) "
        "OR (document_type != 'template' AND template_purpose IS NULL "
        "AND template_channel IS NULL)",
    )
    # Partial unique index: at most one template row per (tenant, purpose,
    # channel) slot. Documents are edited in place (version bumped, see
    # TenantConfigurationRuntime.update_knowledge_document) rather than
    # superseded by a new row, so this never collides with a legitimate
    # content update — only with a genuine duplicate slot.
    op.create_index(
        "uq_tenant_knowledge_documents_template_slot",
        _TABLE,
        ["tenant_id", "template_purpose", "template_channel"],
        unique=True,
        postgresql_where=sa.text("document_type = 'template'"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_tenant_knowledge_documents_template_slot",
        table_name=_TABLE,
    )
    op.drop_constraint(
        op.f("ck_tenant_knowledge_documents_template_fields_match_type"),
        _TABLE,
        type_="check",
    )
    op.drop_column(_TABLE, "template_channel")
    op.drop_column(_TABLE, "template_purpose")
