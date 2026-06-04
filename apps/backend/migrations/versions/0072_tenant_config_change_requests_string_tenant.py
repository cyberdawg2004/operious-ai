"""align change request tenant ids with slug tenant identity

Revision ID: 0072_tenant_config_change_requests_string_tenant
Revises: 0071_connector_config_reconstruction
Create Date: 2026-06-04
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0072_tenant_config_change_requests_string_tenant"
down_revision: Union[str, None] = "0071_connector_config_reconstruction"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "tenant_config_change_requests"
_TENANT_ID_NONEMPTY = "ck_tenant_config_change_requests_tenant_id_nonempty"


def upgrade() -> None:
    _drop_tenant_policy()
    op.alter_column(
        _TABLE,
        "tenant_id",
        existing_type=postgresql.UUID(as_uuid=True),
        type_=sa.String(length=255),
        existing_nullable=False,
        postgresql_using="tenant_id::text",
        schema="public",
    )
    op.create_check_constraint(
        _TENANT_ID_NONEMPTY,
        _TABLE,
        "length(tenant_id) > 0",
        schema="public",
    )
    _create_string_tenant_policy()
    _force_rls()


def downgrade() -> None:
    _drop_tenant_policy()
    op.drop_constraint(
        _TENANT_ID_NONEMPTY,
        _TABLE,
        type_="check",
        schema="public",
    )
    op.alter_column(
        _TABLE,
        "tenant_id",
        existing_type=sa.String(length=255),
        type_=postgresql.UUID(as_uuid=True),
        existing_nullable=False,
        postgresql_using="tenant_id::uuid",
        schema="public",
    )
    _create_uuid_tenant_policy()
    _force_rls()


def _drop_tenant_policy() -> None:
    op.execute(
        "DROP POLICY IF EXISTS tenant_isolation "
        "ON public.tenant_config_change_requests"
    )


def _create_string_tenant_policy() -> None:
    op.execute("""
        CREATE POLICY tenant_isolation
        ON public.tenant_config_change_requests
        USING (
            tenant_id = current_setting('app.current_tenant_id', true)
        )
        WITH CHECK (
            tenant_id = current_setting('app.current_tenant_id', true)
        )
        """)


def _create_uuid_tenant_policy() -> None:
    op.execute("""
        CREATE POLICY tenant_isolation
        ON public.tenant_config_change_requests
        USING (
            tenant_id::text = current_setting('app.current_tenant_id', true)
        )
        WITH CHECK (
            tenant_id::text = current_setting('app.current_tenant_id', true)
        )
        """)


def _force_rls() -> None:
    op.execute("ALTER TABLE public.tenant_config_change_requests FORCE ROW LEVEL SECURITY")
