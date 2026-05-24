"""resolve webhook tenant by routing address

Revision ID: 0033_rls_routing_resolver
Revises: 0033_widen_alembic_version
Create Date: 2026-05-25 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0033_rls_routing_resolver"
down_revision: Union[str, None] = "0033_widen_alembic_version"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.resolve_tenant_by_routing_address(
            p_routing_address text
        )
        RETURNS text
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
            WITH matches AS (
                SELECT tenant_id
                FROM public.tenant_channel_configurations
                WHERE routing_address = p_routing_address
                  AND status = 'active'
                LIMIT 2
            )
            SELECT CASE
                WHEN COUNT(*) = 1 THEN MIN(tenant_id)
                ELSE NULL
            END
            FROM matches
        $$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF current_user = 'neondb_owner' THEN
                ALTER FUNCTION public.resolve_tenant_by_routing_address(text)
                    OWNER TO neondb_owner;
            END IF;
        END
        $$;
        """
    )
    op.execute(
        "REVOKE ALL ON FUNCTION public.resolve_tenant_by_routing_address(text) "
        "FROM PUBLIC"
    )
    _grant_execute_if_role("operious_app")
    _grant_execute_if_role("operious_app_test")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS public.resolve_tenant_by_routing_address(text)")


def _grant_execute_if_role(role_name: str) -> None:
    escaped_role = role_name.replace("'", "''")
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT FROM pg_roles WHERE rolname = '{escaped_role}'
            ) THEN
                EXECUTE format(
                    'GRANT EXECUTE ON FUNCTION public.resolve_tenant_by_routing_address(text) TO %I',
                    '{escaped_role}'
                );
            END IF;
        END
        $$;
        """
    )
