"""create semantic quarantine records

Revision ID: 0056_semantic_quarantine
Revises: 0055_semantic_circuit_events
Create Date: 2026-05-30
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0056_semantic_quarantine"
down_revision: Union[str, None] = "0055_semantic_circuit_events"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "semantic_quarantine_records",
        sa.Column(
            "quarantine_id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("channel", sa.String(length=64), nullable=False),
        sa.Column("original_queue", sa.String(length=255), nullable=False),
        sa.Column("external_id", sa.String(length=512), nullable=True),
        sa.Column(
            "ticket_payload_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "fingerprint_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("cluster_size", sa.Integer(), nullable=False),
        sa.Column("similarity_threshold", sa.Float(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("reviewed_by", sa.String(length=255), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
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
        sa.CheckConstraint(
            "status IN ('pending', 'fraud_confirmed', 'false_positive')",
            name="semantic_quarantine_status_valid",
        ),
        sa.PrimaryKeyConstraint(
            "quarantine_id",
            name=op.f("pk_semantic_quarantine_records"),
        ),
        schema="public",
    )
    op.create_index(
        "ix_semantic_quarantine_tenant_status",
        "semantic_quarantine_records",
        ["tenant_id", "status"],
        unique=False,
        schema="public",
    )
    op.execute(
        "ALTER TABLE public.semantic_quarantine_records ENABLE ROW LEVEL SECURITY"
    )
    op.execute(
        "ALTER TABLE public.semantic_quarantine_records FORCE ROW LEVEL SECURITY"
    )
    op.execute(
        """
        CREATE POLICY tenant_isolation ON public.semantic_quarantine_records
        USING (
            tenant_id = current_setting('app.current_tenant_id', true)
        )
        WITH CHECK (
            tenant_id = current_setting('app.current_tenant_id', true)
        )
        """
    )
    _grant_table_if_role("operious_app", "semantic_quarantine_records")
    _grant_table_if_role("operious_app_test", "semantic_quarantine_records")


def downgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS tenant_isolation "
        "ON public.semantic_quarantine_records"
    )
    op.drop_index(
        "ix_semantic_quarantine_tenant_status",
        table_name="semantic_quarantine_records",
        schema="public",
    )
    op.drop_table("semantic_quarantine_records", schema="public")


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
                    'GRANT SELECT, INSERT, UPDATE ON TABLE public.%I TO %I',
                    '{escaped_table}',
                    '{escaped_role}'
                );
            END IF;
        END
        $$;
        """
    )
