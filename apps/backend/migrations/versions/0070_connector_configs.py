"""per-tenant action connector configs

Revision ID: 0070_connector_configs
Revises: 0069_connector_invocations
Create Date: 2026-06-03
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0070_connector_configs"
down_revision: Union[str, None] = "0069_connector_invocations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "connector_configs"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("connector_type", sa.String(length=255), nullable=False),
        sa.Column("tool_name", sa.String(length=255), nullable=False),
        sa.Column("http_method", sa.String(length=16), nullable=False),
        sa.Column("endpoint_template", sa.Text(), nullable=False),
        sa.Column("endpoint_host", sa.String(length=255), nullable=False),
        sa.Column(
            "field_mappings",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("idempotency_header_name", sa.String(length=128), nullable=False),
        sa.Column(
            "response_parse",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "success_status_codes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[200, 201, 202]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default=sa.text("'active'"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(tenant_id) > 0",
            name=op.f("ck_connector_configs_tenant_id_nonempty"),
        ),
        sa.CheckConstraint(
            "length(connector_type) > 0",
            name=op.f("ck_connector_configs_connector_type_nonempty"),
        ),
        sa.CheckConstraint(
            "length(tool_name) > 0",
            name=op.f("ck_connector_configs_tool_name_nonempty"),
        ),
        sa.CheckConstraint(
            "length(http_method) > 0",
            name=op.f("ck_connector_configs_http_method_nonempty"),
        ),
        sa.CheckConstraint(
            "length(endpoint_template) > 0",
            name=op.f("ck_connector_configs_endpoint_template_nonempty"),
        ),
        sa.CheckConstraint(
            "length(endpoint_host) > 0",
            name=op.f("ck_connector_configs_endpoint_host_nonempty"),
        ),
        sa.CheckConstraint(
            "length(idempotency_header_name) > 0",
            name=op.f("ck_connector_configs_idempotency_header_nonempty"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(field_mappings) = 'object'",
            name=op.f("ck_connector_configs_field_mappings_object"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(response_parse) = 'object'",
            name=op.f("ck_connector_configs_response_parse_object"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(success_status_codes) = 'array'",
            name=op.f("ck_connector_configs_success_status_codes_array"),
        ),
        sa.CheckConstraint(
            "status IN ('active', 'disabled')",
            name=op.f("ck_connector_configs_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.tenant_id"],
            name=op.f("fk_connector_configs_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "tenant_id",
            "connector_type",
            "tool_name",
            name=op.f("pk_connector_configs"),
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "tool_name",
            name=op.f("uq_connector_configs_tenant_tool_name"),
        ),
        schema="public",
    )
    op.create_index(
        op.f("ix_connector_configs_tenant_status"),
        _TABLE,
        ["tenant_id", "status"],
        schema="public",
    )
    op.create_index(
        op.f("ix_connector_configs_tenant_tool"),
        _TABLE,
        ["tenant_id", "tool_name"],
        schema="public",
    )
    _enable_tenant_rls(_TABLE)
    _grant_table_if_role("operious_app", _TABLE)
    _grant_table_if_role("operious_app_test", _TABLE)


def downgrade() -> None:
    op.execute(f"ALTER TABLE public.{_q(_TABLE)} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON public.{_q(_TABLE)}")
    op.drop_index(
        op.f("ix_connector_configs_tenant_tool"),
        table_name=_TABLE,
        schema="public",
    )
    op.drop_index(
        op.f("ix_connector_configs_tenant_status"),
        table_name=_TABLE,
        schema="public",
    )
    op.drop_table(_TABLE, schema="public")


def _enable_tenant_rls(table_name: str) -> None:
    op.execute(f"ALTER TABLE public.{_q(table_name)} ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY tenant_isolation ON public.{_q(table_name)}
        USING (operious_tenant_rls_allows(tenant_id))
        WITH CHECK (operious_tenant_rls_allows(tenant_id))
        """
    )
    op.execute(f"ALTER TABLE public.{_q(table_name)} FORCE ROW LEVEL SECURITY")


def _grant_table_if_role(role_name: str, table_name: str) -> None:
    escaped_role = role_name.replace("'", "''")
    escaped_table = table_name.replace("'", "''")
    op.execute(f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT FROM pg_roles WHERE rolname = '{escaped_role}'
            ) THEN
                EXECUTE format(
                    'GRANT SELECT, INSERT, UPDATE ON TABLE public.%I TO %I',
                    '{escaped_table}',
                    '{escaped_role}'
                );
            END IF;
        END
        $$;
        """)


def _q(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'
