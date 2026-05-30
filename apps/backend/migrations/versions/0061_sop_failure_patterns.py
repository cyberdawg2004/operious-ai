"""create sop failure patterns table

Revision ID: 0061_sop_failure_patterns
Revises: 0060_outbound_dispatch_records
Create Date: 2026-05-30
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0061_sop_failure_patterns"
down_revision: Union[str, None] = "0060_outbound_dispatch_records"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sop_failure_patterns",
        sa.Column("pattern_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("pattern_source", sa.String(length=32), nullable=False),
        sa.Column("category", sa.String(length=255), nullable=False),
        sa.Column("failure_count", sa.Integer(), nullable=False),
        sa.Column("window_hours", sa.Integer(), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("threshold_used", sa.Integer(), nullable=False),
        sa.Column("sop_proposal_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default=sa.text("'detected'"),
            nullable=False,
        ),
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
        sa.PrimaryKeyConstraint(
            "pattern_id",
            name=op.f("pk_sop_failure_patterns"),
        ),
        sa.CheckConstraint(
            "length(tenant_id) > 0",
            name=op.f("ck_sop_failure_patterns_tenant_id_nonempty"),
        ),
        sa.CheckConstraint(
            "pattern_source IN ('dlq', 'admission', 'combined')",
            name=op.f("ck_sop_failure_patterns_source_valid"),
        ),
        sa.CheckConstraint(
            "length(category) > 0",
            name=op.f("ck_sop_failure_patterns_category_nonempty"),
        ),
        sa.CheckConstraint(
            "failure_count >= 0",
            name=op.f("ck_sop_failure_patterns_failure_count_nonnegative"),
        ),
        sa.CheckConstraint(
            "window_hours >= 1",
            name=op.f("ck_sop_failure_patterns_window_positive"),
        ),
        sa.CheckConstraint(
            "threshold_used >= 1",
            name=op.f("ck_sop_failure_patterns_threshold_positive"),
        ),
        sa.CheckConstraint(
            "status IN ('detected', 'proposed', 'acknowledged')",
            name=op.f("ck_sop_failure_patterns_status_valid"),
        ),
        schema="public",
    )
    op.execute(
        """
        CREATE INDEX ix_sop_failure_patterns_tenant_category
        ON public.sop_failure_patterns (tenant_id, category, created_at DESC)
        """
    )
    op.execute(
        "ALTER TABLE public.sop_failure_patterns ENABLE ROW LEVEL SECURITY"
    )
    op.execute(
        "ALTER TABLE public.sop_failure_patterns FORCE ROW LEVEL SECURITY"
    )
    op.execute(
        """
        CREATE POLICY tenant_isolation ON public.sop_failure_patterns
        USING (tenant_id = current_setting('app.current_tenant_id', true))
        WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true))
        """
    )
    _grant_table_if_role("operious_app", "sop_failure_patterns")
    _grant_table_if_role("operious_app_test", "sop_failure_patterns")
    _grant_table_if_role(
        "operious_app",
        "admission_records",
        privileges="SELECT, INSERT",
    )
    _grant_table_if_role(
        "operious_app_test",
        "admission_records",
        privileges="SELECT, INSERT",
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE public.sop_failure_patterns NO FORCE ROW LEVEL SECURITY"
    )
    op.execute(
        "DROP POLICY IF EXISTS tenant_isolation ON public.sop_failure_patterns"
    )
    op.execute(
        "ALTER TABLE public.sop_failure_patterns DISABLE ROW LEVEL SECURITY"
    )
    op.execute(
        "DROP INDEX IF EXISTS public.ix_sop_failure_patterns_tenant_category"
    )
    op.drop_table("sop_failure_patterns", schema="public")


def _grant_table_if_role(
    role_name: str,
    table_name: str,
    *,
    privileges: str = "SELECT, INSERT, UPDATE",
) -> None:
    escaped_role = role_name.replace("'", "''")
    escaped_table = table_name.replace("'", "''")
    escaped_privileges = privileges.replace("'", "''")
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT FROM pg_roles WHERE rolname = '{escaped_role}'
            ) THEN
                EXECUTE format(
                    'GRANT {escaped_privileges} ON TABLE public.%I TO %I',
                    '{escaped_table}',
                    '{escaped_role}'
                );
            END IF;
        END
        $$;
        """
    )
