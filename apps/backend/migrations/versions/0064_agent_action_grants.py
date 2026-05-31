"""create durable agent action grants

Revision ID: 0064_agent_action_grants
Revises: 0063_tenant_config_change_requests
Create Date: 2026-05-31
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0064_agent_action_grants"
down_revision: Union[str, None] = "0063_tenant_config_change_requests"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_action_grants",
        sa.Column("grant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("decision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tool_name", sa.String(length=255), nullable=False),
        sa.Column("action", sa.String(length=96), nullable=False),
        sa.Column("actor", sa.String(length=255), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("binding_hash", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column(
            "issued_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consumed_by", sa.String(length=255), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text('\'{"_schema_version":"1"}\'::jsonb'),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(tenant_id) > 0",
            name=op.f("ck_agent_action_grants_tenant_id_nonempty"),
        ),
        sa.CheckConstraint(
            "length(actor) > 0",
            name=op.f("ck_agent_action_grants_actor_nonempty"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(metadata) = 'object' AND metadata ? '_schema_version'",
            name=op.f("ck_agent_action_grants_metadata_schema_version"),
        ),
        sa.ForeignKeyConstraint(
            ["decision_id"],
            ["governance_decisions.decision_id"],
            name=op.f(
                "fk_agent_action_grants_decision_id_governance_decisions"
            ),
        ),
        sa.PrimaryKeyConstraint(
            "grant_id", name=op.f("pk_agent_action_grants")
        ),
        sa.UniqueConstraint(
            "decision_id", name=op.f("uq_agent_action_grants_decision_id")
        ),
        sa.UniqueConstraint(
            "idempotency_key",
            name=op.f("uq_agent_action_grants_idempotency_key"),
        ),
        schema="public",
    )
    _assert_table_exists()
    op.execute("ALTER TABLE public.agent_action_grants ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON public.agent_action_grants
        USING (
            tenant_id = current_setting('app.current_tenant_id', true)
        )
        WITH CHECK (
            tenant_id = current_setting('app.current_tenant_id', true)
        )
        """
    )
    op.execute("ALTER TABLE public.agent_action_grants FORCE ROW LEVEL SECURITY")
    op.create_index(
        "ix_agent_action_grants_tenant_decision",
        "agent_action_grants",
        ["tenant_id", "decision_id"],
        unique=False,
        schema="public",
    )
    op.create_index(
        "ix_agent_action_grants_tenant_consumed",
        "agent_action_grants",
        ["tenant_id", "consumed_at"],
        unique=False,
        schema="public",
    )
    _grant_table_if_role("operious_app", "agent_action_grants")
    _grant_table_if_role("operious_app_test", "agent_action_grants")


def downgrade() -> None:
    op.execute(
        "ALTER TABLE public.agent_action_grants NO FORCE ROW LEVEL SECURITY"
    )
    op.execute(
        "DROP POLICY IF EXISTS tenant_isolation ON public.agent_action_grants"
    )
    op.execute(
        "ALTER TABLE public.agent_action_grants DISABLE ROW LEVEL SECURITY"
    )
    op.drop_index(
        "ix_agent_action_grants_tenant_consumed",
        table_name="agent_action_grants",
        schema="public",
    )
    op.drop_index(
        "ix_agent_action_grants_tenant_decision",
        table_name="agent_action_grants",
        schema="public",
    )
    op.drop_table("agent_action_grants", schema="public")


def _assert_table_exists() -> None:
    result = op.get_bind().execute(
        sa.text("SELECT to_regclass('public.agent_action_grants')")
    ).scalar()
    if result is None:
        raise RuntimeError(
            "Migration 0064: expected table 'agent_action_grants' "
            "does not exist after create_table"
        )


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
