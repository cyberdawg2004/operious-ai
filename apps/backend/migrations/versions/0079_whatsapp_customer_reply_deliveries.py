"""whatsapp customer reply delivery ledger

Revision ID: 0079_whatsapp_customer_reply_deliveries
Revises: 0078_case_approval_queue
Create Date: 2026-06-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0079_whatsapp_customer_reply_deliveries"
down_revision: str | None = "0078_case_approval_queue"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "whatsapp_customer_reply_deliveries"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("delivery_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("draft_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("proposal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "governance_decision_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("phone_number_id", sa.String(length=255), nullable=False),
        sa.Column("recipient_phone_number", sa.String(length=255), nullable=False),
        sa.Column("draft_body_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("provider_message_id", sa.String(length=255), nullable=True),
        sa.Column("provider_status_code", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
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
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(tenant_id) > 0",
            name=op.f("ck_whatsapp_customer_reply_deliveries_tenant_id_nonempty"),
        ),
        sa.CheckConstraint(
            "length(phone_number_id) > 0",
            name=op.f(
                "ck_whatsapp_customer_reply_deliveries_phone_number_id_nonempty"
            ),
        ),
        sa.CheckConstraint(
            "length(recipient_phone_number) > 0",
            name=op.f("ck_whatsapp_customer_reply_deliveries_recipient_nonempty"),
        ),
        sa.CheckConstraint(
            "length(draft_body_sha256) = 64",
            name=op.f(
                "ck_whatsapp_customer_reply_deliveries_draft_body_sha256_valid"
            ),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'sent', 'failed')",
            name=op.f("ck_whatsapp_customer_reply_deliveries_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.tenant_id"],
            name=op.f(
                "fk_whatsapp_customer_reply_deliveries_tenant_id_tenants"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["draft_id"],
            ["resolution_outbound_drafts.draft_id"],
            name=op.f(
                "fk_whatsapp_customer_reply_deliveries_draft_id_resolution_outbound_drafts"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["proposal_id"],
            ["resolution_proposals.proposal_id"],
            name=op.f(
                "fk_whatsapp_customer_reply_deliveries_proposal_id_resolution_proposals"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["governance_decision_id"],
            ["governance_decisions.decision_id"],
            name=op.f(
                "fk_whatsapp_customer_reply_deliveries_governance_decision_id_governance_decisions"
            ),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "delivery_id",
            name=op.f("pk_whatsapp_customer_reply_deliveries"),
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "draft_id",
            "governance_decision_id",
            name="uq_whatsapp_delivery_tenant_draft_governance",
        ),
        schema="public",
    )
    for column in (
        "tenant_id",
        "draft_id",
        "proposal_id",
        "governance_decision_id",
        "phone_number_id",
        "recipient_phone_number",
        "status",
        "provider_message_id",
    ):
        op.create_index(
            op.f(f"ix_whatsapp_customer_reply_deliveries_{column}"),
            _TABLE,
            [column],
            schema="public",
        )
    op.create_index(
        "ix_whatsapp_delivery_tenant_status",
        _TABLE,
        ["tenant_id", "status"],
        schema="public",
    )
    op.create_index(
        "ix_whatsapp_delivery_tenant_recipient",
        _TABLE,
        ["tenant_id", "recipient_phone_number"],
        schema="public",
    )
    op.create_index(
        "uq_whatsapp_delivery_tenant_provider_message",
        _TABLE,
        ["tenant_id", "provider_message_id"],
        schema="public",
        unique=True,
        postgresql_where=sa.text("provider_message_id IS NOT NULL"),
    )
    _enable_tenant_rls(_TABLE)
    _grant_table_if_role("operious_app", _TABLE)
    _grant_table_if_role("operious_app_test", _TABLE)


def downgrade() -> None:
    op.execute(f"ALTER TABLE public.{_q(_TABLE)} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON public.{_q(_TABLE)}")
    op.drop_index(
        "uq_whatsapp_delivery_tenant_provider_message",
        table_name=_TABLE,
        schema="public",
    )
    op.drop_index(
        "ix_whatsapp_delivery_tenant_recipient",
        table_name=_TABLE,
        schema="public",
    )
    op.drop_index(
        "ix_whatsapp_delivery_tenant_status",
        table_name=_TABLE,
        schema="public",
    )
    for column in (
        "provider_message_id",
        "status",
        "recipient_phone_number",
        "phone_number_id",
        "governance_decision_id",
        "proposal_id",
        "draft_id",
        "tenant_id",
    ):
        op.drop_index(
            op.f(f"ix_whatsapp_customer_reply_deliveries_{column}"),
            table_name=_TABLE,
            schema="public",
        )
    op.drop_table(_TABLE, schema="public")


def _enable_tenant_rls(table_name: str) -> None:
    op.execute(f"ALTER TABLE public.{_q(table_name)} ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY tenant_isolation ON public.{_q(table_name)}
        USING (operious_tenant_rls_allows(tenant_id))
        WITH CHECK (operious_tenant_rls_allows(tenant_id))
        """
    )
    op.execute(f"ALTER TABLE public.{_q(table_name)} FORCE ROW LEVEL SECURITY")


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
                    'GRANT SELECT, INSERT, UPDATE ON TABLE public.%I TO %I',
                    '{escaped_table}',
                    '{escaped_role}'
                );
            END IF;
        END
        $$;
        """
    )


def _q(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'
