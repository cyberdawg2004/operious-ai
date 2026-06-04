"""tenant lifecycle status and platform tenant administration

Revision ID: 0073_tenant_lifecycle
Revises: 0072_tenant_config_change_requests_string_tenant
Create Date: 2026-06-04 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0073_tenant_lifecycle"
down_revision: Union[str, None] = "0072_tenant_config_change_requests_string_tenant"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "tenants"
_PLATFORM_POLICY = "platform_tenant_admin"
_STATUS_CHECK = "ck_tenants_tenant_status_valid"


def upgrade() -> None:
    op.add_column(
        _TABLE,
        sa.Column(
            "status",
            sa.String(length=64),
            server_default=sa.text("'active'"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        _STATUS_CHECK,
        _TABLE,
        "status IN ('active', 'provisioning', 'disabled')",
    )
    op.create_index(op.f("ix_tenants_status"), _TABLE, ["status"])
    op.execute(f"DROP POLICY IF EXISTS {_PLATFORM_POLICY} ON public.{_TABLE}")
    op.execute(f"""
        CREATE POLICY {_PLATFORM_POLICY}
        ON public.{_TABLE}
        USING (
            current_setting('app.platform_tenant_admin', true) = 'true'
        )
        WITH CHECK (
            current_setting('app.platform_tenant_admin', true) = 'true'
        )
        """)
    op.execute(f"ALTER TABLE public.{_TABLE} FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute(f"DROP POLICY IF EXISTS {_PLATFORM_POLICY} ON public.{_TABLE}")
    op.drop_index(op.f("ix_tenants_status"), table_name=_TABLE)
    op.drop_constraint(_STATUS_CHECK, _TABLE, type_="check")
    op.drop_column(_TABLE, "status")
