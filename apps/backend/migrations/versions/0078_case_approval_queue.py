"""create SME case approval queue

Revision ID: 0078_case_approval_queue
Revises: 0077_escalation_handoff_kind_priority
Create Date: 2026-06-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0078_case_approval_queue"
down_revision: str | None = "0077_escalation_handoff_kind_priority"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "case_approval_records",
        sa.Column("approval_case_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("execution_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("dispatch_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "resolution_proposal_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("entry_category", sa.String(length=64), nullable=False),
        sa.Column("ticket_ref", sa.String(length=255), nullable=True),
        sa.Column("product", sa.String(length=255), nullable=True),
        sa.Column("issue_summary", sa.Text(), nullable=True),
        sa.Column(
            "sme_recommendation_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "recommended_action",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column(
            "guidance_round",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("guidance_ref", sa.Text(), nullable=True),
        sa.Column(
            "governance_decision_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.String(length=255), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("dedup_key", sa.String(length=255), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.CheckConstraint("length(tenant_id) > 0", name="tenant_id_nonempty"),
        sa.CheckConstraint("length(dedup_key) > 0", name="dedup_key_nonempty"),
        sa.CheckConstraint(
            "entry_category IN ("
            "'resolution_require_approval', "
            "'resolution_needs_human_approval', "
            "'refund_warranty', "
            "'low_confidence', "
            "'coordination_human_review', "
            "'crisis_action')",
            name="case_approval_entry_category_valid",
        ),
        sa.CheckConstraint(
            "status IN ("
            "'pending_sme_review', "
            "'awaiting_approval', "
            "'guidance_in_progress', "
            "'approved', "
            "'escalated', "
            "'failed')",
            name="case_approval_status_valid",
        ),
        sa.CheckConstraint(
            "guidance_round IN (0, 1)",
            name="case_approval_guidance_round_valid",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.tenant_id"],
            name=op.f("fk_case_approval_records_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["operational_sessions.session_id"],
            name=op.f(
                "fk_case_approval_records_session_id_operational_sessions"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["resolution_proposal_id"],
            ["resolution_proposals.proposal_id"],
            name=op.f(
                "fk_case_approval_records_resolution_proposal_id_resolution_proposals"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["governance_decision_id"],
            ["governance_decisions.decision_id"],
            name=op.f(
                "fk_case_approval_records_governance_decision_id_governance_decisions"
            ),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "approval_case_id",
            name=op.f("pk_case_approval_records"),
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "dedup_key",
            name="uq_case_approval_records_tenant_dedup",
        ),
        schema="public",
    )
    for column in (
        "tenant_id",
        "session_id",
        "execution_id",
        "dispatch_id",
        "resolution_proposal_id",
        "entry_category",
        "ticket_ref",
        "sme_recommendation_id",
        "status",
        "governance_decision_id",
        "requested_at",
        "resolved_by",
    ):
        op.create_index(
            op.f(f"ix_case_approval_records_{column}"),
            "case_approval_records",
            [column],
            schema="public",
        )
    op.create_index(
        "ix_case_approval_records_tenant_status_requested",
        "case_approval_records",
        ["tenant_id", "status", "requested_at"],
        schema="public",
    )
    op.create_table(
        "case_approval_outbox",
        sa.Column("outbox_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("approval_case_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claim_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("publisher_id", sa.String(length=255), nullable=True),
        sa.Column("republish_count", sa.Integer(), nullable=False),
        sa.Column("dead_letter", sa.Boolean(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.CheckConstraint("length(tenant_id) > 0", name="tenant_id_nonempty"),
        sa.CheckConstraint(
            "status IN ('pending', 'publishing', 'published', 'failed')",
            name="case_approval_outbox_status_valid",
        ),
        sa.CheckConstraint(
            "republish_count >= 0",
            name="case_approval_outbox_republish_count_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["approval_case_id"],
            ["case_approval_records.approval_case_id"],
            name=op.f(
                "fk_case_approval_outbox_approval_case_id_case_approval_records"
            ),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.tenant_id"],
            name=op.f("fk_case_approval_outbox_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("outbox_id", name=op.f("pk_case_approval_outbox")),
        sa.UniqueConstraint(
            "approval_case_id",
            name="uq_case_approval_outbox_approval_case_id",
        ),
        schema="public",
    )
    for column in (
        "approval_case_id",
        "tenant_id",
        "status",
        "created_at",
        "claimed_at",
        "published_at",
        "claim_id",
        "publisher_id",
    ):
        op.create_index(
            op.f(f"ix_case_approval_outbox_{column}"),
            "case_approval_outbox",
            [column],
            schema="public",
        )
    op.create_index(
        "ix_case_approval_outbox_tenant_status",
        "case_approval_outbox",
        ["tenant_id", "status"],
        schema="public",
    )
    for table in ("case_approval_records", "case_approval_outbox"):
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation ON public.{table}
            USING (operious_tenant_rls_allows(tenant_id))
            WITH CHECK (operious_tenant_rls_allows(tenant_id))
            """
        )
        op.execute(f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY")
        _grant_table_if_role("operious_app", table)
        _grant_table_if_role("operious_app_test", table)


def downgrade() -> None:
    for table in ("case_approval_outbox", "case_approval_records"):
        op.execute(f"ALTER TABLE public.{table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON public.{table}")
        op.execute(f"ALTER TABLE public.{table} DISABLE ROW LEVEL SECURITY")
    op.drop_index(
        "ix_case_approval_outbox_tenant_status",
        table_name="case_approval_outbox",
        schema="public",
    )
    for column in (
        "publisher_id",
        "claim_id",
        "published_at",
        "claimed_at",
        "created_at",
        "status",
        "tenant_id",
        "approval_case_id",
    ):
        op.drop_index(
            op.f(f"ix_case_approval_outbox_{column}"),
            table_name="case_approval_outbox",
            schema="public",
        )
    op.drop_table("case_approval_outbox", schema="public")
    op.drop_index(
        "ix_case_approval_records_tenant_status_requested",
        table_name="case_approval_records",
        schema="public",
    )
    for column in (
        "resolved_by",
        "requested_at",
        "governance_decision_id",
        "status",
        "sme_recommendation_id",
        "ticket_ref",
        "entry_category",
        "resolution_proposal_id",
        "dispatch_id",
        "execution_id",
        "session_id",
        "tenant_id",
    ):
        op.drop_index(
            op.f(f"ix_case_approval_records_{column}"),
            table_name="case_approval_records",
            schema="public",
        )
    op.drop_table("case_approval_records", schema="public")


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
