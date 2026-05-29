"""create crisis deployments

Revision ID: 0053_crisis_deployments
Revises: 0052_boundary_ingress_language
Create Date: 2026-05-30
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0053_crisis_deployments"
down_revision: Union[str, None] = "0052_boundary_ingress_language"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "crisis_deployments",
        sa.Column("deployment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("template", sa.String(length=64), nullable=False),
        sa.Column(
            "scope_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "ttl_minutes",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("policy_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("deployed_by", sa.String(length=255), nullable=False),
        sa.Column(
            "deployed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default=sa.text("'active'"),
            nullable=False,
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("deployment_id", name=op.f("pk_crisis_deployments")),
        schema="public",
    )
    op.create_index(
        "ix_crisis_deployments_tenant_status",
        "crisis_deployments",
        ["tenant_id", "status"],
        unique=False,
        schema="public",
    )
    op.execute("ALTER TABLE public.crisis_deployments ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.crisis_deployments FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON public.crisis_deployments
        USING (
            tenant_id = current_setting('app.current_tenant_id', true)
        )
        WITH CHECK (
            tenant_id = current_setting('app.current_tenant_id', true)
        )
        """
    )
    _grant_table_if_role("operious_app", "crisis_deployments")
    _grant_table_if_role("operious_app_test", "crisis_deployments")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON public.crisis_deployments")
    op.drop_index(
        "ix_crisis_deployments_tenant_status",
        table_name="crisis_deployments",
        schema="public",
    )
    op.drop_table("crisis_deployments", schema="public")


def _grant_table_if_role(role_name: str, table_name: str) -> None:
    escaped_role = role_name.replace("'", "''")
    escaped_table = table_name.replace("'", "''")
    op.execute(
        f"""
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
        """
    )
