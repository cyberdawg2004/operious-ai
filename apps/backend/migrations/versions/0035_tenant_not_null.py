"""enforce tenant id not null

Revision ID: 0035_tenant_not_null
Revises: 0034_force_rls
Create Date: 2026-05-25 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0035_tenant_not_null"
down_revision: Union[str, None] = "0034_force_rls"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TENANT_NOT_NULL_TABLES = (
    "arbitration_evaluations",
    "boundary_egress",
    "boundary_ingress",
    "coordination_envelopes",
    "governance_decisions",
    "governance_traces",
    "operational_events",
    "operational_sessions",
    "supervisor_inspections",
)


def upgrade() -> None:
    for table_name in _TENANT_NOT_NULL_TABLES:
        op.execute(
            f'ALTER TABLE public."{table_name}" '
            "ALTER COLUMN tenant_id SET NOT NULL"
        )


def downgrade() -> None:
    for table_name in reversed(_TENANT_NOT_NULL_TABLES):
        op.execute(
            f'ALTER TABLE public."{table_name}" '
            "ALTER COLUMN tenant_id DROP NOT NULL"
        )
