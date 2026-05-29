"""create semantic circuit events

Revision ID: 0055_semantic_circuit_events
Revises: 0054_crisis_events
Create Date: 2026-05-30
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0055_semantic_circuit_events"
down_revision: Union[str, None] = "0054_crisis_events"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "semantic_circuit_events",
        sa.Column(
            "event_id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("channel", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("trigger_ticket_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("cluster_size", sa.Integer(), nullable=True),
        sa.Column("similarity_threshold", sa.Float(), nullable=True),
        sa.Column("window_seconds", sa.Integer(), nullable=True),
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
        sa.PrimaryKeyConstraint(
            "event_id",
            name=op.f("pk_semantic_circuit_events"),
        ),
        schema="public",
    )
    op.create_index(
        "ix_semantic_circuit_events_tenant_channel",
        "semantic_circuit_events",
        ["tenant_id", "channel", sa.text("occurred_at DESC")],
        unique=False,
        schema="public",
    )
    op.execute("ALTER TABLE public.semantic_circuit_events ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.semantic_circuit_events FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON public.semantic_circuit_events
        USING (
            tenant_id = current_setting('app.current_tenant_id', true)
        )
        """)
    op.execute("""
        COMMENT ON TABLE public.semantic_circuit_events IS
        'Append-only semantic circuit audit trail. UPDATE and DELETE are blocked by trigger.'
        """)
    op.execute("""
        CREATE OR REPLACE FUNCTION public.prevent_semantic_circuit_events_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'semantic_circuit_events is append-only';
        END;
        $$;
        """)
    op.execute("""
        CREATE TRIGGER semantic_circuit_events_append_only
        BEFORE UPDATE OR DELETE ON public.semantic_circuit_events
        FOR EACH ROW EXECUTE FUNCTION public.prevent_semantic_circuit_events_mutation()
        """)
    _grant_table_if_role("operious_app", "semantic_circuit_events")
    _grant_table_if_role("operious_app_test", "semantic_circuit_events")


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS semantic_circuit_events_append_only "
        "ON public.semantic_circuit_events"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS " "public.prevent_semantic_circuit_events_mutation()"
    )
    op.execute(
        "DROP POLICY IF EXISTS tenant_isolation " "ON public.semantic_circuit_events"
    )
    op.drop_index(
        "ix_semantic_circuit_events_tenant_channel",
        table_name="semantic_circuit_events",
        schema="public",
    )
    op.drop_table("semantic_circuit_events", schema="public")


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
                    'GRANT SELECT, INSERT ON TABLE public.%I TO %I',
                    '{escaped_table}',
                    '{escaped_role}'
                );
            END IF;
        END
        $$;
        """)
