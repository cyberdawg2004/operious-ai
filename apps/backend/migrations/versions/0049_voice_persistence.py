"""create voice persistence tables

Revision ID: 0049_voice_persistence
Revises: 0048_session_external_handle_idx
Create Date: 2026-05-29
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0049_voice_persistence"
down_revision: Union[str, None] = "0048_session_external_handle_idx"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "voice_ingress_records",
        sa.Column("record_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("direction", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("transcript_text", sa.Text(), nullable=True),
        sa.Column("audio_handle_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("provider_kind", sa.String(length=64), nullable=True),
        sa.Column("provider_model", sa.String(length=128), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("fingerprint_sha256", sa.String(length=64), nullable=True),
        sa.Column("lineage_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "runtime_instance_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "record_id", name=op.f("pk_voice_ingress_records")
        ),
        schema="public",
    )
    op.execute(
        "ALTER TABLE public.voice_ingress_records ENABLE ROW LEVEL SECURITY"
    )
    op.execute(
        """
        CREATE POLICY tenant_isolation ON public.voice_ingress_records
        USING (
            tenant_id = current_setting('app.current_tenant_id', true)
        )
        WITH CHECK (
            tenant_id = current_setting('app.current_tenant_id', true)
        )
        """
    )
    op.execute(
        "ALTER TABLE public.voice_ingress_records FORCE ROW LEVEL SECURITY"
    )
    op.create_index(
        "ix_voice_ingress_records_tenant_session",
        "voice_ingress_records",
        ["tenant_id", "session_id"],
        unique=False,
        schema="public",
    )
    op.create_index(
        "ix_voice_ingress_records_tenant_created_at",
        "voice_ingress_records",
        ["tenant_id", sa.text("created_at DESC")],
        unique=False,
        schema="public",
    )

    op.create_table(
        "voice_egress_records",
        sa.Column("record_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("direction", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("synthesis_text", sa.Text(), nullable=True),
        sa.Column("audio_handle_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("provider_kind", sa.String(length=64), nullable=True),
        sa.Column("provider_model", sa.String(length=128), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("fingerprint_sha256", sa.String(length=64), nullable=True),
        sa.Column("lineage_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "runtime_instance_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "governance_decision_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "record_id", name=op.f("pk_voice_egress_records")
        ),
        schema="public",
    )
    op.execute(
        "ALTER TABLE public.voice_egress_records ENABLE ROW LEVEL SECURITY"
    )
    op.execute(
        """
        CREATE POLICY tenant_isolation ON public.voice_egress_records
        USING (
            tenant_id = current_setting('app.current_tenant_id', true)
        )
        WITH CHECK (
            tenant_id = current_setting('app.current_tenant_id', true)
        )
        """
    )
    op.execute(
        "ALTER TABLE public.voice_egress_records FORCE ROW LEVEL SECURITY"
    )
    op.create_index(
        "ix_voice_egress_records_tenant_session",
        "voice_egress_records",
        ["tenant_id", "session_id"],
        unique=False,
        schema="public",
    )
    op.create_index(
        "ix_voice_egress_records_tenant_created_at",
        "voice_egress_records",
        ["tenant_id", sa.text("created_at DESC")],
        unique=False,
        schema="public",
    )

    for table_name in ("voice_ingress_records", "voice_egress_records"):
        _grant_table_if_role("operious_app", table_name)
        _grant_table_if_role("operious_app_test", table_name)


def downgrade() -> None:
    for table_name in ("voice_egress_records", "voice_ingress_records"):
        op.execute(
            f"ALTER TABLE public.{table_name} NO FORCE ROW LEVEL SECURITY"
        )
        op.execute(
            f"DROP POLICY IF EXISTS tenant_isolation ON public.{table_name}"
        )
        op.execute(
            f"ALTER TABLE public.{table_name} DISABLE ROW LEVEL SECURITY"
        )

    op.drop_index(
        "ix_voice_egress_records_tenant_created_at",
        table_name="voice_egress_records",
        schema="public",
    )
    op.drop_index(
        "ix_voice_egress_records_tenant_session",
        table_name="voice_egress_records",
        schema="public",
    )
    op.drop_table("voice_egress_records", schema="public")

    op.drop_index(
        "ix_voice_ingress_records_tenant_created_at",
        table_name="voice_ingress_records",
        schema="public",
    )
    op.drop_index(
        "ix_voice_ingress_records_tenant_session",
        table_name="voice_ingress_records",
        schema="public",
    )
    op.drop_table("voice_ingress_records", schema="public")


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
