"""SME/MVP-3: add metadata column to resolution_proposals.

Revision ID: 0096_sme_resolution_proposal_metadata
Revises: 0095_mvp6_semantic_qa_grounding
Create Date: 2026-07-04

Adds a JSONB metadata column to resolution_proposals. This column stores
structured context that doesn't warrant a dedicated typed column:

  gate_reasons: list[str]
    Gate reasons from _evaluate_gate() (e.g. "fraud_risk_high",
    "safety_risk"). Used by the SME approval routing to determine entry
    category (FRAUD_RISK_HIGH routes to dedicated SME fraud queue).
    Populated by resolution_runtime.py at proposal creation time.
    Pre-migration rows backfill to {} (empty metadata = no reasons).

This is the same metadata pattern used by resolution_outbound_drafts
and other tables in the platform.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0096_sme_resolution_proposal_metadata"
down_revision: Union[str, None] = "0095_mvp6_semantic_qa_grounding"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "resolution_proposals",
        sa.Column(
            "metadata",
            pg.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        schema="public",
    )


def downgrade() -> None:
    op.drop_column("resolution_proposals", "metadata", schema="public")
