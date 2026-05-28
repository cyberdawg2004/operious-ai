"""add governance decision lineage to resolution proposals

Revision ID: 0043_resolution_proposal_governance_decision
Revises: 0042_resolution_proposal_tenant_fk
Create Date: 2026-05-28
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0043_resolution_proposal_governance_decision"
down_revision: Union[str, None] = "0042_resolution_proposal_tenant_fk"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "resolution_proposals",
        sa.Column(
            "governance_decision_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        schema="public",
    )
    op.create_index(
        "ix_resolution_proposals_tenant_governance_decision",
        "resolution_proposals",
        ["tenant_id", "governance_decision_id"],
        unique=False,
        schema="public",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_resolution_proposals_tenant_governance_decision",
        table_name="resolution_proposals",
        schema="public",
    )
    op.drop_column(
        "resolution_proposals",
        "governance_decision_id",
        schema="public",
    )
