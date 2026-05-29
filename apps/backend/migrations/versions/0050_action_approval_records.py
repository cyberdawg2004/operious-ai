"""create action approval records table

Revision ID: 0050_action_approval_records
Revises: 0049_voice_persistence
Create Date: 2026-05-29
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0050_action_approval_records"
down_revision: Union[str, None] = "0049_voice_persistence"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "action_approval_records",
        sa.Column(
            "approval_id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("execution_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("tool_name", sa.String(length=255), nullable=False),
        sa.Column("idempotency_key", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "payload_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "governance_decision_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.String(length=64),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.String(length=255), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "approval_id", name=op.f("pk_action_approval_records")
        ),
        sa.UniqueConstraint(
            "idempotency_key",
            name=op.f("uq_action_approval_records_idempotency_key"),
        ),
        schema="public",
    )
    op.execute(
        "ALTER TABLE public.action_approval_records ENABLE ROW LEVEL SECURITY"
    )
    op.execute(
        """
        CREATE POLICY tenant_isolation ON public.action_approval_records
        USING (
            tenant_id = current_setting('app.current_tenant_id', true)
        )
        WITH CHECK (
            tenant_id = current_setting('app.current_tenant_id', true)
        )
        """
    )
    op.execute(
        "ALTER TABLE public.action_approval_records FORCE ROW LEVEL SECURITY"
    )
    op.create_index(
        "ix_action_approvals_tenant_status",
        "action_approval_records",
        ["tenant_id", "status"],
        unique=False,
        schema="public",
    )
    op.create_index(
        "ix_action_approvals_tenant_session",
        "action_approval_records",
        ["tenant_id", "session_id"],
        unique=False,
        schema="public",
    )
    _grant_table_if_role("operious_app", "action_approval_records")
    _grant_table_if_role("operious_app_test", "action_approval_records")


def downgrade() -> None:
    op.execute(
        "ALTER TABLE public.action_approval_records NO FORCE ROW LEVEL SECURITY"
    )
    op.execute(
        "DROP POLICY IF EXISTS tenant_isolation ON public.action_approval_records"
    )
    op.execute(
        "ALTER TABLE public.action_approval_records DISABLE ROW LEVEL SECURITY"
    )
    op.drop_index(
        "ix_action_approvals_tenant_session",
        table_name="action_approval_records",
        schema="public",
    )
    op.drop_index(
        "ix_action_approvals_tenant_status",
        table_name="action_approval_records",
        schema="public",
    )
    op.drop_table("action_approval_records", schema="public")


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
