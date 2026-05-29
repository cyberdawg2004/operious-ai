"""create training recommendations table

Revision ID: 0051_training_recommendations
Revises: 0050_action_approval_records
Create Date: 2026-05-29
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0051_training_recommendations"
down_revision: Union[str, None] = "0050_action_approval_records"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "training_recommendations",
        sa.Column(
            "recommendation_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("qa_score_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("category", sa.String(length=255), nullable=False),
        sa.Column("finding_summary", sa.Text(), nullable=False),
        sa.Column("recommendation", sa.Text(), nullable=False),
        sa.Column(
            "priority",
            sa.String(length=32),
            server_default=sa.text("'medium'"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default=sa.text("'pending'"),
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
            "recommendation_id",
            name=op.f("pk_training_recommendations"),
        ),
        sa.CheckConstraint(
            "length(tenant_id) > 0",
            name=op.f("ck_training_recommendations_tenant_id_nonempty"),
        ),
        sa.CheckConstraint(
            "length(category) > 0",
            name=op.f("ck_training_recommendations_category_nonempty"),
        ),
        sa.CheckConstraint(
            "priority IN ('low', 'medium', 'high')",
            name=op.f("ck_training_recommendations_priority_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'acknowledged', 'applied', 'dismissed')",
            name=op.f("ck_training_recommendations_status_valid"),
        ),
        schema="public",
    )
    op.execute(
        "ALTER TABLE public.training_recommendations ENABLE ROW LEVEL SECURITY"
    )
    op.execute(
        """
        CREATE POLICY tenant_isolation ON public.training_recommendations
        USING (
            tenant_id = current_setting('app.current_tenant_id', true)
        )
        WITH CHECK (
            tenant_id = current_setting('app.current_tenant_id', true)
        )
        """
    )
    op.execute(
        "ALTER TABLE public.training_recommendations FORCE ROW LEVEL SECURITY"
    )
    op.create_index(
        "ix_training_recs_tenant_status",
        "training_recommendations",
        ["tenant_id", "status"],
        unique=False,
        schema="public",
    )
    op.create_index(
        "ix_training_recs_tenant_category_created",
        "training_recommendations",
        ["tenant_id", "category", "created_at"],
        unique=False,
        schema="public",
    )
    _grant_table_if_role("operious_app", "training_recommendations")
    _grant_table_if_role("operious_app_test", "training_recommendations")


def downgrade() -> None:
    op.execute(
        "ALTER TABLE public.training_recommendations NO FORCE ROW LEVEL SECURITY"
    )
    op.execute(
        "DROP POLICY IF EXISTS tenant_isolation ON public.training_recommendations"
    )
    op.execute(
        "ALTER TABLE public.training_recommendations DISABLE ROW LEVEL SECURITY"
    )
    op.drop_index(
        "ix_training_recs_tenant_category_created",
        table_name="training_recommendations",
        schema="public",
    )
    op.drop_index(
        "ix_training_recs_tenant_status",
        table_name="training_recommendations",
        schema="public",
    )
    op.drop_table("training_recommendations", schema="public")


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
