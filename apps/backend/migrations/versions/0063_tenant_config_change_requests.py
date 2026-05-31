"""create tenant config change request ledger

Revision ID: 0063_tenant_config_change_requests
Revises: 0062_webhook_routing_secret_resolver
Create Date: 2026-05-31
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

revision: str = "0063_tenant_config_change_requests"
down_revision: Union[str, None] = "0062_webhook_routing_secret_resolver"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLE_NAME = "tenant_config_change_requests"


def upgrade() -> None:
    op.create_table(
        _TABLE_NAME,
        sa.Column(
            "change_request_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("change_type", sa.Text(), nullable=False),
        sa.Column(
            "proposed_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Text(),
            server_default=sa.text("'PROPOSED'"),
            nullable=False,
        ),
        sa.Column("proposed_by", sa.Text(), nullable=False),
        sa.Column("proposed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_by", sa.Text(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_by", sa.Text(), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column(
            "outcome_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.CheckConstraint(
            "change_type IN ("
            "'knowledge', 'policy', 'execution_governance', "
            "'topology', 'channel'"
            ")",
            name=op.f("ck_tenant_config_change_requests_change_type_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('PROPOSED', 'APPROVED', 'REJECTED', 'APPLIED')",
            name=op.f("ck_tenant_config_change_requests_status_valid"),
        ),
        sa.CheckConstraint(
            "approved_by IS NULL OR approved_by != proposed_by",
            name=op.f("ck_tenant_config_change_requests_approver_distinct"),
        ),
        sa.PrimaryKeyConstraint(
            "change_request_id",
            name=op.f("pk_tenant_config_change_requests"),
        ),
        schema="public",
    )
    _assert_table_exists()
    op.execute(
        "ALTER TABLE public.tenant_config_change_requests " "ENABLE ROW LEVEL SECURITY"
    )
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
    op.execute(
        "ALTER TABLE public.tenant_config_change_requests " "FORCE ROW LEVEL SECURITY"
    )
    op.create_index(
        "ix_tenant_config_change_requests_tenant_status",
        _TABLE_NAME,
        ["tenant_id", "status"],
        unique=False,
        schema="public",
    )
    _grant_table_if_role("operious_app", _TABLE_NAME)
    _grant_table_if_role("operious_app_test", _TABLE_NAME)


def downgrade() -> None:
    op.execute(
        "ALTER TABLE public.tenant_config_change_requests "
        "NO FORCE ROW LEVEL SECURITY"
    )
    op.execute(
        "DROP POLICY IF EXISTS tenant_isolation "
        "ON public.tenant_config_change_requests"
    )
    op.execute(
        "ALTER TABLE public.tenant_config_change_requests " "DISABLE ROW LEVEL SECURITY"
    )
    op.drop_index(
        "ix_tenant_config_change_requests_tenant_status",
        table_name=_TABLE_NAME,
        schema="public",
    )
    op.drop_table(_TABLE_NAME, schema="public")


def _assert_table_exists() -> None:
    conn = op.get_bind()
    result = conn.execute(
        text("SELECT to_regclass(:qualified_table)"),
        {"qualified_table": f"public.{_TABLE_NAME}"},
    ).scalar()
    if result is None:
        raise RuntimeError(
            "Migration 0063: expected table "
            f"'public.{_TABLE_NAME}' does not exist. Cannot apply FORCE RLS."
        )


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
                    'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.%I TO %I',
                    '{escaped_table}',
                    '{escaped_role}'
                );
            END IF;
        END
        $$;
        """)
