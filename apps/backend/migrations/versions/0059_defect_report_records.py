"""defect report records

Revision ID: 0059_defect_report_records
Revises: 0058_execution_diagnostic_category
Create Date: 2026-05-30 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0059_defect_report_records"
down_revision: Union[str, None] = "0058_execution_diagnostic_category"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "defect_report_records",
        sa.Column("report_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("cluster_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("executive_summary", sa.Text(), nullable=False),
        sa.Column("failure_pattern", sa.Text(), nullable=False),
        sa.Column("customer_impact", sa.Text(), nullable=False),
        sa.Column("root_cause_hypothesis", sa.Text(), nullable=False),
        sa.Column(
            "recommended_actions",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("evidence_quality", sa.String(length=16), nullable=False),
        sa.Column("incident_count", sa.Integer(), nullable=False),
        sa.Column("governance_decision_id", postgresql.UUID(as_uuid=True)),
        sa.Column(
            "governance_status",
            sa.String(length=32),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("llm_model", sa.String(length=128), nullable=True),
        sa.Column("cognition_audit_id", postgresql.UUID(as_uuid=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(tenant_id) > 0",
            name=op.f("ck_defect_report_records_tenant_id_nonempty"),
        ),
        sa.CheckConstraint(
            "confidence >= 0.0 AND confidence <= 1.0",
            name=op.f("ck_defect_report_records_confidence_range"),
        ),
        sa.CheckConstraint(
            "incident_count >= 1",
            name=op.f("ck_defect_report_records_incident_count_positive"),
        ),
        sa.CheckConstraint(
            "evidence_quality IN ('high', 'medium', 'low')",
            name=op.f("ck_defect_report_records_evidence_quality_valid"),
        ),
        sa.CheckConstraint(
            "governance_status IN ('pending', 'allowed', 'blocked')",
            name=op.f("ck_defect_report_records_governance_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["cluster_id"],
            ["defect_cluster_records.cluster_id"],
            name=op.f("fk_defect_report_records_cluster_id_defect_cluster_records"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.tenant_id"],
            name=op.f("fk_defect_report_records_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "report_id",
            name=op.f("pk_defect_report_records"),
        ),
    )
    op.create_index(
        "ix_defect_reports_tenant_cluster",
        "defect_report_records",
        ["tenant_id", "cluster_id"],
    )
    op.execute("ALTER TABLE defect_report_records ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE defect_report_records FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON defect_report_records
        USING (tenant_id = current_setting('app.current_tenant_id', true))
        WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true))
        """
    )
    _grant_table_if_role("operious_app", "defect_report_records")
    _grant_table_if_role("operious_app_test", "defect_report_records")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON defect_report_records")
    op.drop_index(
        "ix_defect_reports_tenant_cluster",
        table_name="defect_report_records",
    )
    op.drop_table("defect_report_records")


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
