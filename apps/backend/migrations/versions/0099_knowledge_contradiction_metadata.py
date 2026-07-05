"""Add contradiction_metadata JSONB column to tenant_knowledge_documents.

Revision ID: 0099_knowledge_contradiction_metadata
Revises: 0098_connector_callback_hmac_secret
Create Date: 2026-07-05

Adds a nullable JSONB column ``contradiction_metadata`` to
``tenant_knowledge_documents``. This column stores the structured
contradiction report produced by SOPContradictionAgent (MVP-4) when a
document is quarantined due to a detected conflict with the existing KB.

The metadata includes:
  contradiction_flagged: bool
  contradiction_count: int
  contradicting_doc_ids: list[str]
  highest_confidence: float
  contradiction_types: list[str]  (direct_conflict | scope_overlap | temporal_conflict)

Pre-migration rows default to NULL (no contradiction check was run or result
was not applicable). A NULL value is not the same as a clean check — the
check status is captured separately in the document's quarantine reason.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0099_knowledge_contradiction_metadata"
down_revision: Union[str, None] = "0098_connector_callback_hmac_secret"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tenant_knowledge_documents",
        sa.Column(
            "contradiction_metadata",
            pg.JSONB(),
            nullable=True,
            comment=(
                "MVP-4 contradiction report metadata. NULL = not checked or not applicable. "
                "Set when SOPContradictionAgent quarantines a document."
            ),
        ),
    )


def downgrade() -> None:
    op.drop_column("tenant_knowledge_documents", "contradiction_metadata")
