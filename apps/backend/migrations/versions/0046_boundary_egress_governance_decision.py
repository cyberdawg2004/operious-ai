"""add egress governance decision lineage

Revision ID: 0046_boundary_egress_governance_decision
Revises: 0045_admission_telemetry_status
Create Date: 2026-05-29

The column is intentionally nullable at the database layer because
historical boundary_egress rows have no backfillable persisted
governance decision. New emits are fail-closed in BoundaryEgressRuntime
and BoundaryEgressRecord serialization before rows are persisted.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0046_boundary_egress_governance_decision"
down_revision: Union[str, None] = "0045_admission_telemetry_status"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "boundary_egress",
        sa.Column(
            "governance_decision_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        schema="public",
    )
    op.create_index(
        "ix_boundary_egress_tenant_governance_decision",
        "boundary_egress",
        ["tenant_id", "governance_decision_id"],
        unique=False,
        schema="public",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_boundary_egress_tenant_governance_decision",
        table_name="boundary_egress",
        schema="public",
    )
    op.drop_column(
        "boundary_egress",
        "governance_decision_id",
        schema="public",
    )
