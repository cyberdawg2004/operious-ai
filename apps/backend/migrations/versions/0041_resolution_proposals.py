"""create resolution proposals

Revision ID: 0041_resolution_proposals
Revises: 0040_pgvector
Create Date: 2026-05-28
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0041_resolution_proposals"
down_revision: Union[str, None] = "0040_pgvector"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "resolution_proposals",
        sa.Column(
            "proposal_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "execution_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "dispatch_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "diagnostic_event_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("proposed_customer_reply", sa.Text(), nullable=False),
        sa.Column(
            "resolution_category",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column(
            "recommended_actions",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "evidence",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "supervisor_verdict",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "governance_verdict",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "autonomy_decision",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=64), nullable=False),
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
            name=op.f("ck_resolution_proposals_tenant_id_nonempty"),
        ),
        sa.CheckConstraint(
            "length(proposed_customer_reply) > 0",
            name=op.f(
                "ck_resolution_proposals_resolution_proposal_reply_nonempty"
            ),
        ),
        sa.CheckConstraint(
            "length(resolution_category) > 0",
            name=op.f(
                "ck_resolution_proposals_resolution_proposal_category_nonempty"
            ),
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name=op.f(
                "ck_resolution_proposals_resolution_proposal_confidence_bounds"
            ),
        ),
        sa.CheckConstraint(
            "autonomy_decision IN "
            "('auto_approved', 'needs_customer_info', "
            "'needs_human_approval', 'denied')",
            name=op.f(
                "ck_resolution_proposals_resolution_proposal_autonomy_decision_valid"
            ),
        ),
        sa.CheckConstraint(
            "status IN "
            "('proposed', 'auto_approved', 'send_eligible', "
            "'pending_human_approval', 'denied', 'failed')",
            name=op.f(
                "ck_resolution_proposals_resolution_proposal_status_valid"
            ),
        ),
        sa.CheckConstraint(
            "supervisor_verdict IN "
            "('pass', 'needs_human_review', 'fail')",
            name=op.f(
                "ck_resolution_proposals_resolution_proposal_supervisor_verdict_valid"
            ),
        ),
        sa.CheckConstraint(
            "governance_verdict IN "
            "('allow', 'require_approval', 'escalate', 'deny', "
            "'degrade', 'redact')",
            name=op.f(
                "ck_resolution_proposals_resolution_proposal_governance_verdict_valid"
            ),
        ),
        sa.PrimaryKeyConstraint(
            "proposal_id",
            name=op.f("pk_resolution_proposals"),
        ),
    )
    op.create_index(
        op.f("ix_resolution_proposals_tenant_id"),
        "resolution_proposals",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_resolution_proposals_session_id"),
        "resolution_proposals",
        ["session_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_resolution_proposals_execution_id"),
        "resolution_proposals",
        ["execution_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_resolution_proposals_dispatch_id"),
        "resolution_proposals",
        ["dispatch_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_resolution_proposals_diagnostic_event_id"),
        "resolution_proposals",
        ["diagnostic_event_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_resolution_proposals_resolution_category"),
        "resolution_proposals",
        ["resolution_category"],
        unique=False,
    )
    op.create_index(
        op.f("ix_resolution_proposals_supervisor_verdict"),
        "resolution_proposals",
        ["supervisor_verdict"],
        unique=False,
    )
    op.create_index(
        op.f("ix_resolution_proposals_governance_verdict"),
        "resolution_proposals",
        ["governance_verdict"],
        unique=False,
    )
    op.create_index(
        op.f("ix_resolution_proposals_autonomy_decision"),
        "resolution_proposals",
        ["autonomy_decision"],
        unique=False,
    )
    op.create_index(
        op.f("ix_resolution_proposals_status"),
        "resolution_proposals",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_resolution_proposals_tenant_session",
        "resolution_proposals",
        ["tenant_id", "session_id"],
        unique=False,
    )
    op.create_index(
        "ix_resolution_proposals_tenant_execution",
        "resolution_proposals",
        ["tenant_id", "execution_id"],
        unique=False,
    )
    op.create_index(
        "ix_resolution_proposals_tenant_status",
        "resolution_proposals",
        ["tenant_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_resolution_proposals_tenant_created_at",
        "resolution_proposals",
        ["tenant_id", "created_at"],
        unique=False,
    )
    op.execute(
        "ALTER TABLE public.resolution_proposals ENABLE ROW LEVEL SECURITY"
    )
    op.execute(
        """
        CREATE POLICY tenant_isolation ON public.resolution_proposals
        USING (operious_tenant_rls_allows(tenant_id))
        WITH CHECK (operious_tenant_rls_allows(tenant_id))
        """
    )
    op.execute(
        "ALTER TABLE public.resolution_proposals FORCE ROW LEVEL SECURITY"
    )
    _grant_table_if_role("operious_app")
    _grant_table_if_role("operious_app_test")


def downgrade() -> None:
    op.execute(
        "ALTER TABLE public.resolution_proposals NO FORCE ROW LEVEL SECURITY"
    )
    op.execute(
        "DROP POLICY IF EXISTS tenant_isolation ON public.resolution_proposals"
    )
    op.execute(
        "ALTER TABLE public.resolution_proposals DISABLE ROW LEVEL SECURITY"
    )
    op.drop_index(
        "ix_resolution_proposals_tenant_created_at",
        table_name="resolution_proposals",
    )
    op.drop_index(
        "ix_resolution_proposals_tenant_status",
        table_name="resolution_proposals",
    )
    op.drop_index(
        "ix_resolution_proposals_tenant_execution",
        table_name="resolution_proposals",
    )
    op.drop_index(
        "ix_resolution_proposals_tenant_session",
        table_name="resolution_proposals",
    )
    op.drop_index(
        op.f("ix_resolution_proposals_status"),
        table_name="resolution_proposals",
    )
    op.drop_index(
        op.f("ix_resolution_proposals_autonomy_decision"),
        table_name="resolution_proposals",
    )
    op.drop_index(
        op.f("ix_resolution_proposals_governance_verdict"),
        table_name="resolution_proposals",
    )
    op.drop_index(
        op.f("ix_resolution_proposals_supervisor_verdict"),
        table_name="resolution_proposals",
    )
    op.drop_index(
        op.f("ix_resolution_proposals_resolution_category"),
        table_name="resolution_proposals",
    )
    op.drop_index(
        op.f("ix_resolution_proposals_diagnostic_event_id"),
        table_name="resolution_proposals",
    )
    op.drop_index(
        op.f("ix_resolution_proposals_dispatch_id"),
        table_name="resolution_proposals",
    )
    op.drop_index(
        op.f("ix_resolution_proposals_execution_id"),
        table_name="resolution_proposals",
    )
    op.drop_index(
        op.f("ix_resolution_proposals_session_id"),
        table_name="resolution_proposals",
    )
    op.drop_index(
        op.f("ix_resolution_proposals_tenant_id"),
        table_name="resolution_proposals",
    )
    op.drop_table("resolution_proposals")


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
                    'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.resolution_proposals TO %I',
                    '{escaped_role}'
                );
            END IF;
        END
        $$;
        """
    )
