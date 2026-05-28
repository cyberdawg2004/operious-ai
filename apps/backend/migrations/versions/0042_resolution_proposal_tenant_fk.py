"""add tenant foreign key for resolution proposals

Revision ID: 0042_resolution_proposal_tenant_fk
Revises: 0041_resolution_proposals
Create Date: 2026-05-28
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0042_resolution_proposal_tenant_fk"
down_revision: Union[str, None] = "0041_resolution_proposals"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_FK_NAME = "fk_resolution_proposals_tenant_id_tenants"


def upgrade() -> None:
    bind = op.get_bind()
    orphan_rows = bind.execute(
        sa.text(
            """
            SELECT rp.tenant_id
            FROM public.resolution_proposals AS rp
            LEFT JOIN public.tenants AS t
              ON t.tenant_id = rp.tenant_id
            WHERE t.tenant_id IS NULL
            GROUP BY rp.tenant_id
            ORDER BY rp.tenant_id
            LIMIT 10
            """
        )
    ).scalars().all()
    if orphan_rows:
        tenants = ", ".join(str(tenant_id) for tenant_id in orphan_rows)
        raise RuntimeError(
            "cannot add resolution_proposals tenant FK; orphan "
            f"tenant_id values exist: {tenants}"
        )

    op.create_foreign_key(
        _FK_NAME,
        "resolution_proposals",
        "tenants",
        ["tenant_id"],
        ["tenant_id"],
        source_schema="public",
        referent_schema="public",
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        _FK_NAME,
        "resolution_proposals",
        schema="public",
        type_="foreignkey",
    )
