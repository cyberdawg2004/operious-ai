"""scope webhook routing resolver by channel type

Revision ID: 0062_webhook_routing_secret_resolver
Revises: 0061_sop_failure_patterns
Create Date: 2026-05-30
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "0062_webhook_routing_secret_resolver"
down_revision: Union[str, None] = "0061_sop_failure_patterns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "DROP FUNCTION IF EXISTS "
        "public.resolve_tenant_by_routing_address(text)"
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.resolve_tenant_by_routing_address(
            p_channel_type text,
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
                WHERE channel_type = p_channel_type
                  AND routing_address = p_routing_address
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
        CREATE OR REPLACE FUNCTION public.resolve_webhook_routing_secret(
            p_channel_type text,
            p_routing_address text
        )
        RETURNS TABLE (
            tenant_id text,
            config_id uuid,
            channel_type text,
            routing_address text,
            webhook_secret text,
            previous_webhook_secret text,
            credential_rotation_expires_at timestamptz
        )
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
            WITH matches AS (
                SELECT
                    tcc.tenant_id::text,
                    tcc.config_id,
                    tcc.channel_type::text,
                    tcc.routing_address::text,
                    tcc.webhook_secret::text,
                    tcc.previous_webhook_secret::text,
                    tcc.credential_rotation_expires_at
                FROM public.tenant_channel_configurations tcc
                WHERE tcc.channel_type = p_channel_type
                  AND tcc.routing_address = p_routing_address
                  AND tcc.status = 'active'
                LIMIT 2
            ),
            counted AS (
                SELECT COUNT(*) AS match_count FROM matches
            )
            SELECT
                matches.tenant_id,
                matches.config_id,
                matches.channel_type,
                matches.routing_address,
                matches.webhook_secret,
                matches.previous_webhook_secret,
                matches.credential_rotation_expires_at
            FROM matches, counted
            WHERE counted.match_count = 1
        $$;
        """
    )
    _alter_owner_if_neon("resolve_tenant_by_routing_address(text, text)")
    _alter_owner_if_neon("resolve_webhook_routing_secret(text, text)")
    op.execute(
        "REVOKE ALL ON FUNCTION "
        "public.resolve_tenant_by_routing_address(text, text) FROM PUBLIC"
    )
    op.execute(
        "REVOKE ALL ON FUNCTION "
        "public.resolve_webhook_routing_secret(text, text) FROM PUBLIC"
    )
    _grant_execute_if_role(
        "resolve_tenant_by_routing_address(text, text)",
        "operious_app",
    )
    _grant_execute_if_role(
        "resolve_tenant_by_routing_address(text, text)",
        "operious_app_test",
    )
    _grant_execute_if_role(
        "resolve_webhook_routing_secret(text, text)",
        "operious_app",
    )
    _grant_execute_if_role(
        "resolve_webhook_routing_secret(text, text)",
        "operious_app_test",
    )


def downgrade() -> None:
    op.execute(
        "DROP FUNCTION IF EXISTS "
        "public.resolve_webhook_routing_secret(text, text)"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS "
        "public.resolve_tenant_by_routing_address(text, text)"
    )
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
    _alter_owner_if_neon("resolve_tenant_by_routing_address(text)")
    op.execute(
        "REVOKE ALL ON FUNCTION "
        "public.resolve_tenant_by_routing_address(text) FROM PUBLIC"
    )
    _grant_execute_if_role(
        "resolve_tenant_by_routing_address(text)",
        "operious_app",
    )
    _grant_execute_if_role(
        "resolve_tenant_by_routing_address(text)",
        "operious_app_test",
    )


def _alter_owner_if_neon(function_signature: str) -> None:
    escaped_signature = function_signature.replace("'", "''")
    op.execute(
        f"""
        DO $$
        BEGIN
            IF current_user = 'neondb_owner' THEN
                EXECUTE 'ALTER FUNCTION public.{escaped_signature}
                    OWNER TO neondb_owner';
            END IF;
        END
        $$;
        """
    )


def _grant_execute_if_role(function_signature: str, role_name: str) -> None:
    escaped_signature = function_signature.replace("'", "''")
    escaped_role = role_name.replace("'", "''")
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT FROM pg_roles WHERE rolname = '{escaped_role}'
            ) THEN
                EXECUTE format(
                    'GRANT EXECUTE ON FUNCTION public.{escaped_signature} TO %I',
                    '{escaped_role}'
                );
            END IF;
        END
        $$;
        """
    )
