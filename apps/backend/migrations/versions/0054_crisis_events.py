"""create crisis events

Revision ID: 0054_crisis_events
Revises: 0053_crisis_deployments
Create Date: 2026-05-30
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0054_crisis_events"
down_revision: Union[str, None] = "0053_crisis_deployments"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "crisis_events",
        sa.Column(
            "event_id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("deployment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_kind", sa.String(length=32), nullable=False),
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
        sa.Column("actor", sa.String(length=255), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["deployment_id"],
            ["public.crisis_deployments.deployment_id"],
            name=op.f("fk_crisis_events_deployment_id_crisis_deployments"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("event_id", name=op.f("pk_crisis_events")),
        schema="public",
    )
    op.create_index(
        "ix_crisis_events_tenant_occurred",
        "crisis_events",
        ["tenant_id", sa.text("occurred_at DESC")],
        unique=False,
        schema="public",
    )
    op.create_index(
        "ix_crisis_events_deployment",
        "crisis_events",
        ["deployment_id"],
        unique=False,
        schema="public",
    )
    op.execute("ALTER TABLE public.crisis_events ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.crisis_events FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON public.crisis_events
        USING (
            tenant_id = current_setting('app.current_tenant_id', true)
        )
        """
    )
    op.execute(
        """
        COMMENT ON TABLE public.crisis_events IS
        'Append-only crisis audit trail. Direct UPDATE and DELETE are blocked; owning deployment deletion cascades events.'
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.prevent_crisis_events_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF TG_OP = 'DELETE' AND pg_trigger_depth() > 1 THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION 'crisis_events is append-only';
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER crisis_events_append_only
        BEFORE UPDATE OR DELETE ON public.crisis_events
        FOR EACH ROW EXECUTE FUNCTION public.prevent_crisis_events_mutation()
        """
    )
    _grant_table_if_role("operious_app", "crisis_events")
    _grant_table_if_role("operious_app_test", "crisis_events")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS crisis_events_append_only ON public.crisis_events")
    op.execute("DROP FUNCTION IF EXISTS public.prevent_crisis_events_mutation()")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON public.crisis_events")
    op.drop_index(
        "ix_crisis_events_deployment",
        table_name="crisis_events",
        schema="public",
    )
    op.drop_index(
        "ix_crisis_events_tenant_occurred",
        table_name="crisis_events",
        schema="public",
    )
    op.drop_table("crisis_events", schema="public")


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
                    'GRANT SELECT, INSERT ON TABLE public.%I TO %I',
                    '{escaped_table}',
                    '{escaped_role}'
                );
            END IF;
        END
        $$;
        """
    )
