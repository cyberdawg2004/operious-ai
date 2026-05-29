"""execution diagnostic category and defect clusters

Revision ID: 0058_execution_diagnostic_category
Revises: 0057_resolution_fk_constraints
Create Date: 2026-05-30 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0058_execution_diagnostic_category"
down_revision: Union[str, None] = "0057_resolution_fk_constraints"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "execution_records",
        sa.Column("diagnostic_category", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "execution_records",
        sa.Column("diagnostic_confidence", sa.Float(), nullable=True),
    )
    op.execute(
        """
        UPDATE execution_records
        SET
            diagnostic_category = COALESCE(
                result ->> 'diagnostic_category',
                result ->> 'category'
            ),
            diagnostic_confidence = CASE
                WHEN COALESCE(
                    result ->> 'diagnostic_confidence',
                    result ->> 'confidence'
                ) ~ '^-?[0-9]+(\\.[0-9]+)?$'
                THEN COALESCE(
                    result ->> 'diagnostic_confidence',
                    result ->> 'confidence'
                )::double precision
                ELSE NULL
            END
        WHERE state = 'completed'
          AND COALESCE(
              result ->> 'diagnostic_category',
              result ->> 'category'
          ) IS NOT NULL
        """
    )
    op.create_index(
        "ix_execution_records_tenant_category",
        "execution_records",
        ["tenant_id", "diagnostic_category"],
        postgresql_where=sa.text("diagnostic_category IS NOT NULL"),
    )
    op.create_index(
        "ix_execution_records_category_requested_at",
        "execution_records",
        ["diagnostic_category", sa.text("requested_at DESC")],
        postgresql_where=sa.text("diagnostic_category IS NOT NULL"),
    )

    op.create_table(
        "defect_cluster_records",
        sa.Column(
            "cluster_id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("category", sa.String(length=255), nullable=False),
        sa.Column("execution_count", sa.Integer(), nullable=False),
        sa.Column("window_hours", sa.Integer(), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("threshold_used", sa.Integer(), nullable=False),
        sa.Column("sku_hint", sa.String(length=255), nullable=True),
        sa.Column("failure_step_hint", sa.String(length=255), nullable=True),
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
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(tenant_id) > 0",
            name=op.f("ck_defect_cluster_records_tenant_id_nonempty"),
        ),
        sa.CheckConstraint(
            "length(category) > 0",
            name=op.f("ck_defect_cluster_records_category_nonempty"),
        ),
        sa.CheckConstraint(
            "execution_count >= 0",
            name=op.f("ck_defect_cluster_records_execution_count_nonnegative"),
        ),
        sa.CheckConstraint(
            "window_hours >= 1",
            name=op.f("ck_defect_cluster_records_window_hours_positive"),
        ),
        sa.CheckConstraint(
            "threshold_used >= 1",
            name=op.f("ck_defect_cluster_records_threshold_used_positive"),
        ),
        sa.CheckConstraint(
            "status IN ('detected', 'reported', 'resolved')",
            name=op.f("ck_defect_cluster_records_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.tenant_id"],
            name=op.f("fk_defect_cluster_records_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "cluster_id",
            name=op.f("pk_defect_cluster_records"),
        ),
    )
    op.create_index(
        "ix_defect_clusters_tenant_category",
        "defect_cluster_records",
        ["tenant_id", "category", sa.text("created_at DESC")],
    )
    op.execute("ALTER TABLE defect_cluster_records ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE defect_cluster_records FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON defect_cluster_records
        USING (tenant_id = current_setting('app.current_tenant_id', true))
        WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true))
        """
    )
    _grant_table_if_role("operious_app", "defect_cluster_records")
    _grant_table_if_role("operious_app_test", "defect_cluster_records")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON defect_cluster_records")
    op.drop_index(
        "ix_defect_clusters_tenant_category",
        table_name="defect_cluster_records",
    )
    op.drop_table("defect_cluster_records")
    op.drop_index(
        "ix_execution_records_category_requested_at",
        table_name="execution_records",
    )
    op.drop_index(
        "ix_execution_records_tenant_category",
        table_name="execution_records",
    )
    op.drop_column("execution_records", "diagnostic_confidence")
    op.drop_column("execution_records", "diagnostic_category")


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
