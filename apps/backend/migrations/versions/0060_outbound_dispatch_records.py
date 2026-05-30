"""outbound dispatch records

Revision ID: 0060_outbound_dispatch_records
Revises: 0059_defect_report_records
Create Date: 2026-05-30 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0060_outbound_dispatch_records"
down_revision: Union[str, None] = "0059_defect_report_records"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "outbound_dispatch_records",
        sa.Column(
            "dispatch_id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("report_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("channel_type", sa.String(length=32), nullable=False),
        sa.Column("target_url", sa.String(length=1024), nullable=False),
        sa.Column(
            "attempt_number",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("http_status_code", sa.Integer(), nullable=True),
        sa.Column("response_body", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(tenant_id) > 0",
            name=op.f("ck_outbound_dispatch_records_tenant_id_nonempty"),
        ),
        sa.CheckConstraint(
            "length(channel_type) > 0",
            name=op.f("ck_outbound_dispatch_records_channel_type_nonempty"),
        ),
        sa.CheckConstraint(
            "length(target_url) > 0",
            name=op.f("ck_outbound_dispatch_records_target_url_nonempty"),
        ),
        sa.CheckConstraint(
            "attempt_number >= 1",
            name=op.f("ck_outbound_dispatch_records_attempt_positive"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'success', 'failed', 'dead_lettered')",
            name=op.f("ck_outbound_dispatch_records_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["report_id"],
            ["defect_report_records.report_id"],
            name=op.f(
                "fk_outbound_dispatch_records_report_id_defect_report_records"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.tenant_id"],
            name=op.f("fk_outbound_dispatch_records_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "dispatch_id",
            name=op.f("pk_outbound_dispatch_records"),
        ),
    )
    op.create_index(
        "ix_outbound_dispatch_report_id",
        "outbound_dispatch_records",
        ["report_id", "attempt_number"],
    )
    op.create_index(
        "ix_outbound_dispatch_tenant_status",
        "outbound_dispatch_records",
        ["tenant_id", "status"],
    )
    op.execute("ALTER TABLE outbound_dispatch_records ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE outbound_dispatch_records FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON outbound_dispatch_records
        USING (tenant_id = current_setting('app.current_tenant_id', true))
        WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true))
        """
    )
    _grant_table_if_role("operious_app", "outbound_dispatch_records")
    _grant_table_if_role("operious_app_test", "outbound_dispatch_records")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON outbound_dispatch_records")
    op.drop_index(
        "ix_outbound_dispatch_tenant_status",
        table_name="outbound_dispatch_records",
    )
    op.drop_index(
        "ix_outbound_dispatch_report_id",
        table_name="outbound_dispatch_records",
    )
    op.drop_table("outbound_dispatch_records")


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
