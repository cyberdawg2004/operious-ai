"""Ledger applied_by + REVOKED status + revoke fields (spec 1a #5, #22)

Revision ID: 0066_tenant_config_change_request_revocation
Revises: 0065_knowledge_review_status
Create Date: 2026-06-01
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0066_tenant_config_change_request_revocation"
down_revision: Union[str, None] = "0065_knowledge_review_status"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add applied_by: who applied the change (attribution for durable audit, #5).
    op.add_column(
        "tenant_config_change_requests",
        sa.Column("applied_by", sa.String(255), nullable=True),
    )

    # Add revocation fields: who revoked an APPROVED request and when (#22).
    op.add_column(
        "tenant_config_change_requests",
        sa.Column("revoked_by", sa.String(255), nullable=True),
    )
    op.add_column(
        "tenant_config_change_requests",
        sa.Column(
            "revoked_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    # Widen the status valid constraint to include REVOKED.
    # Postgres requires DROP + re-ADD to modify a CHECK constraint.
    op.drop_constraint(
        "status_valid",
        "tenant_config_change_requests",
        type_="check",
    )
    op.create_check_constraint(
        "status_valid",
        "tenant_config_change_requests",
        "status IN ('PROPOSED', 'APPROVED', 'REJECTED', 'APPLIED', 'REVOKED')",
    )

    # Attribution integrity: new APPLIED rows must carry the applier identity.
    # Existing APPLIED rows (no applied_by) remain valid — the constraint only
    # gates future writes. Service-layer validation is the primary guard.
    op.create_check_constraint(
        "chk_applied_by_when_applied",
        "tenant_config_change_requests",
        "status != 'APPLIED' OR applied_by IS NOT NULL",
    )

    # Revocation integrity: REVOKED rows must carry the revoker identity.
    op.create_check_constraint(
        "chk_revoked_by_when_revoked",
        "tenant_config_change_requests",
        "status != 'REVOKED' OR revoked_by IS NOT NULL",
    )

    op.execute(
        """
        COMMENT ON COLUMN tenant_config_change_requests.applied_by IS
        'Principal who applied this change request (migration 0066). NULL on pre-existing APPLIED rows.'
        """
    )
    op.execute(
        """
        COMMENT ON COLUMN tenant_config_change_requests.revoked_by IS
        'Principal who revoked this APPROVED change request (migration 0066).'
        """
    )


def downgrade() -> None:
    op.drop_constraint(
        "chk_revoked_by_when_revoked",
        "tenant_config_change_requests",
        type_="check",
    )
    op.drop_constraint(
        "chk_applied_by_when_applied",
        "tenant_config_change_requests",
        type_="check",
    )
    op.drop_constraint("status_valid", "tenant_config_change_requests", type_="check")
    op.create_check_constraint(
        "status_valid",
        "tenant_config_change_requests",
        "status IN ('PROPOSED', 'APPROVED', 'REJECTED', 'APPLIED')",
    )
    op.drop_column("tenant_config_change_requests", "revoked_at")
    op.drop_column("tenant_config_change_requests", "revoked_by")
    op.drop_column("tenant_config_change_requests", "applied_by")
