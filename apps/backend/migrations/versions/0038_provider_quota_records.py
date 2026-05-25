"""provider quota records and provider circuit RLS

Revision ID: 0038_provider_quota
Revises: 0037_admission_records_rls
Create Date: 2026-05-25
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0038_provider_quota"
down_revision: Union[str, None] = "0037_admission_records_rls"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "provider_quota_records",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("quota_type", sa.Text(), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "window_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("quota_limit", sa.Integer(), nullable=False),
        sa.Column(
            "is_exhausted",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("operator_circuit_state", sa.Text(), nullable=True),
        sa.Column("operator_set_by", sa.Text(), nullable=True),
        sa.Column("operator_set_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("operator_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_provider_quota_records")),
    )
    op.create_index(
        "ix_provider_quota_tenant_provider_model",
        "provider_quota_records",
        ["tenant_id", "provider", "model"],
    )
    op.execute("ALTER TABLE public.provider_quota_records ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON public.provider_quota_records
        USING (operious_tenant_rls_allows(tenant_id))
        WITH CHECK (operious_tenant_rls_allows(tenant_id))
        """
    )
    op.execute("ALTER TABLE public.provider_quota_records FORCE ROW LEVEL SECURITY")

    op.execute("ALTER TABLE public.provider_circuit_states ENABLE ROW LEVEL SECURITY")
    op.execute(
        "DROP POLICY IF EXISTS tenant_isolation ON public.provider_circuit_states"
    )
    op.execute(
        """
        CREATE POLICY tenant_isolation ON public.provider_circuit_states
        USING (operious_tenant_rls_allows(tenant_id))
        WITH CHECK (operious_tenant_rls_allows(tenant_id))
        """
    )
    op.execute("ALTER TABLE public.provider_circuit_states FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("ALTER TABLE public.provider_circuit_states NO FORCE ROW LEVEL SECURITY")
    op.execute(
        "DROP POLICY IF EXISTS tenant_isolation ON public.provider_circuit_states"
    )
    op.execute("ALTER TABLE public.provider_circuit_states DISABLE ROW LEVEL SECURITY")

    op.execute("ALTER TABLE public.provider_quota_records NO FORCE ROW LEVEL SECURITY")
    op.execute(
        "DROP POLICY IF EXISTS tenant_isolation ON public.provider_quota_records"
    )
    op.execute("ALTER TABLE public.provider_quota_records DISABLE ROW LEVEL SECURITY")
    op.drop_index(
        "ix_provider_quota_tenant_provider_model",
        table_name="provider_quota_records",
    )
    op.drop_table("provider_quota_records")
