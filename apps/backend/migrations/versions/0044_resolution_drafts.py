"""create resolution outbound drafts

Revision ID: 0044_resolution_drafts
Revises: 0043_resolution_proposal_governance_decision
Create Date: 2026-05-28
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0044_resolution_drafts"
down_revision: Union[str, None] = "0043_resolution_proposal_governance_decision"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "resolution_outbound_drafts",
        sa.Column("draft_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("proposal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("execution_id", sa.String(length=64), nullable=False),
        sa.Column("dispatch_id", sa.String(length=64), nullable=False),
        sa.Column("diagnostic_event_id", sa.String(length=64), nullable=True),
        sa.Column(
            "governance_decision_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("draft_body", sa.Text(), nullable=False),
        sa.Column("draft_body_sha256", sa.String(length=64), nullable=False),
        sa.Column("resolution_category", sa.String(length=64), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(tenant_id) > 0",
            name=op.f("ck_resolution_outbound_drafts_draft_tenant_id_nonempty"),
        ),
        sa.CheckConstraint(
            "length(session_id) > 0",
            name=op.f(
                "ck_resolution_outbound_drafts_resolution_outbound_draft_session_id_nonempty"
            ),
        ),
        sa.CheckConstraint(
            "length(execution_id) > 0",
            name=op.f(
                "ck_resolution_outbound_drafts_resolution_outbound_draft_execution_id_nonempty"
            ),
        ),
        sa.CheckConstraint(
            "length(dispatch_id) > 0",
            name=op.f(
                "ck_resolution_outbound_drafts_resolution_outbound_draft_dispatch_id_nonempty"
            ),
        ),
        sa.CheckConstraint(
            "status IN "
            "('ready', 'pending_human_approval', 'denied', 'failed')",
            name=op.f(
                "ck_resolution_outbound_drafts_resolution_outbound_draft_status_valid"
            ),
        ),
        sa.CheckConstraint(
            "length(draft_body) > 0",
            name=op.f(
                "ck_resolution_outbound_drafts_resolution_outbound_draft_body_nonempty"
            ),
        ),
        sa.CheckConstraint(
            "length(draft_body_sha256) = 64",
            name=op.f(
                "ck_resolution_outbound_drafts_resolution_outbound_draft_body_sha256_valid"
            ),
        ),
        sa.CheckConstraint(
            "length(resolution_category) > 0",
            name=op.f(
                "ck_resolution_outbound_drafts_resolution_outbound_draft_category_nonempty"
            ),
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name=op.f(
                "ck_resolution_outbound_drafts_resolution_outbound_draft_confidence_bounds"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.tenant_id"],
            name=op.f("fk_resolution_outbound_drafts_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "draft_id",
            name=op.f("pk_resolution_outbound_drafts"),
        ),
        schema="public",
    )
    op.create_index(
        op.f("ix_resolution_outbound_drafts_tenant_id"),
        "resolution_outbound_drafts",
        ["tenant_id"],
        unique=False,
        schema="public",
    )
    op.create_index(
        op.f("ix_resolution_outbound_drafts_proposal_id"),
        "resolution_outbound_drafts",
        ["proposal_id"],
        unique=False,
        schema="public",
    )
    op.create_index(
        "ix_resolution_outbound_drafts_tenant_proposal",
        "resolution_outbound_drafts",
        ["tenant_id", "proposal_id"],
        unique=False,
        schema="public",
    )
    op.create_index(
        "ix_resolution_outbound_drafts_tenant_status",
        "resolution_outbound_drafts",
        ["tenant_id", "status"],
        unique=False,
        schema="public",
    )
    op.create_index(
        "ix_resolution_outbound_drafts_tenant_created_at",
        "resolution_outbound_drafts",
        ["tenant_id", "created_at"],
        unique=False,
        schema="public",
    )
    op.execute(
        "ALTER TABLE public.resolution_outbound_drafts ENABLE ROW LEVEL SECURITY"
    )
    op.execute(
        """
        CREATE POLICY tenant_isolation ON public.resolution_outbound_drafts
        USING (operious_tenant_rls_allows(tenant_id))
        WITH CHECK (operious_tenant_rls_allows(tenant_id))
        """
    )
    op.execute(
        "ALTER TABLE public.resolution_outbound_drafts FORCE ROW LEVEL SECURITY"
    )
    _grant_table_if_role("operious_app")
    _grant_table_if_role("operious_app_test")


def downgrade() -> None:
    op.execute(
        "ALTER TABLE public.resolution_outbound_drafts NO FORCE ROW LEVEL SECURITY"
    )
    op.execute(
        "DROP POLICY IF EXISTS tenant_isolation ON public.resolution_outbound_drafts"
    )
    op.execute(
        "ALTER TABLE public.resolution_outbound_drafts DISABLE ROW LEVEL SECURITY"
    )
    op.drop_index(
        "ix_resolution_outbound_drafts_tenant_created_at",
        table_name="resolution_outbound_drafts",
        schema="public",
    )
    op.drop_index(
        "ix_resolution_outbound_drafts_tenant_status",
        table_name="resolution_outbound_drafts",
        schema="public",
    )
    op.drop_index(
        "ix_resolution_outbound_drafts_tenant_proposal",
        table_name="resolution_outbound_drafts",
        schema="public",
    )
    op.drop_index(
        op.f("ix_resolution_outbound_drafts_proposal_id"),
        table_name="resolution_outbound_drafts",
        schema="public",
    )
    op.drop_index(
        op.f("ix_resolution_outbound_drafts_tenant_id"),
        table_name="resolution_outbound_drafts",
        schema="public",
    )
    op.drop_table("resolution_outbound_drafts", schema="public")


def _grant_table_if_role(role_name: str) -> None:
    escaped_role = role_name.replace("'", "''")
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT FROM pg_roles WHERE rolname = '{escaped_role}'
            ) THEN
                EXECUTE format(
                    'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.resolution_outbound_drafts TO %I',
                    '{escaped_role}'
                );
            END IF;
        END
        $$;
        """
    )
