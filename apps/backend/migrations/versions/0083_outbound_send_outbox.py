"""durable governed outbound send outbox

Revision ID: 0083_outbound_send_outbox
Revises: 0082_ingress_dispatch_outbox_cascade_fk
Create Date: 2026-06-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0083_outbound_send_outbox"
down_revision: str | None = "0082_ingress_dispatch_outbox_cascade_fk"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "outbound_send_outbox"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("outbox_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("action", sa.String(length=255), nullable=False),
        sa.Column("draft_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("proposal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", sa.String(length=255), nullable=False),
        sa.Column("dispatch_id", sa.String(length=255), nullable=False),
        sa.Column(
            "governance_decision_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("recipient", sa.String(length=255), nullable=False),
        sa.Column("draft_body_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("claim_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("worker_id", sa.String(length=255), nullable=True),
        sa.Column(
            "attempt_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_message_id", sa.String(length=255), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.CheckConstraint(
            "length(tenant_id) > 0",
            name=op.f("ck_outbound_send_outbox_tenant_id_nonempty"),
        ),
        sa.CheckConstraint(
            "channel IN ('email', 'whatsapp')",
            name=op.f("ck_outbound_send_outbox_channel_valid"),
        ),
        sa.CheckConstraint(
            "length(action) > 0",
            name=op.f("ck_outbound_send_outbox_action_nonempty"),
        ),
        sa.CheckConstraint(
            "length(session_id) > 0",
            name=op.f("ck_outbound_send_outbox_session_id_nonempty"),
        ),
        sa.CheckConstraint(
            "length(dispatch_id) > 0",
            name=op.f("ck_outbound_send_outbox_dispatch_id_nonempty"),
        ),
        sa.CheckConstraint(
            "length(recipient) > 0",
            name=op.f("ck_outbound_send_outbox_recipient_nonempty"),
        ),
        sa.CheckConstraint(
            "length(draft_body_sha256) = 64",
            name=op.f("ck_outbound_send_outbox_draft_body_sha256_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'claimed', 'sent', 'dead_lettered')",
            name=op.f("ck_outbound_send_outbox_status_valid"),
        ),
        sa.CheckConstraint(
            "attempt_count >= 0",
            name=op.f("ck_outbound_send_outbox_attempt_count_nonnegative"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.tenant_id"],
            name=op.f("fk_outbound_send_outbox_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["draft_id"],
            ["resolution_outbound_drafts.draft_id"],
            name=op.f(
                "fk_outbound_send_outbox_draft_id_resolution_outbound_drafts"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["proposal_id"],
            ["resolution_proposals.proposal_id"],
            name=op.f("fk_outbound_send_outbox_proposal_id_resolution_proposals"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["governance_decision_id"],
            ["governance_decisions.decision_id"],
            name=op.f(
                "fk_outbound_send_outbox_governance_decision_id_governance_decisions"
            ),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "outbox_id",
            name=op.f("pk_outbound_send_outbox"),
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "draft_id",
            "channel",
            "recipient",
            "action",
            name="uq_outbound_send_outbox_tenant_draft_channel_recipient_action",
        ),
        schema="public",
    )
    for column in (
        "tenant_id",
        "channel",
        "action",
        "draft_id",
        "proposal_id",
        "session_id",
        "dispatch_id",
        "governance_decision_id",
        "recipient",
        "status",
        "claim_id",
        "next_attempt_at",
        "claimed_at",
        "provider_message_id",
    ):
        op.create_index(
            op.f(f"ix_outbound_send_outbox_{column}"),
            _TABLE,
            [column],
            schema="public",
        )
    op.create_index(
        "ix_outbound_send_outbox_status_next_attempt",
        _TABLE,
        ["status", "next_attempt_at"],
        schema="public",
    )
    op.create_index(
        "ix_outbound_send_outbox_tenant_status",
        _TABLE,
        ["tenant_id", "status"],
        schema="public",
    )
    op.create_index(
        "uq_outbound_send_outbox_tenant_provider_message",
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
        "uq_outbound_send_outbox_tenant_provider_message",
        table_name=_TABLE,
        schema="public",
    )
    op.drop_index(
        "ix_outbound_send_outbox_tenant_status",
        table_name=_TABLE,
        schema="public",
    )
    op.drop_index(
        "ix_outbound_send_outbox_status_next_attempt",
        table_name=_TABLE,
        schema="public",
    )
    for column in (
        "provider_message_id",
        "claimed_at",
        "next_attempt_at",
        "claim_id",
        "status",
        "recipient",
        "governance_decision_id",
        "dispatch_id",
        "session_id",
        "proposal_id",
        "draft_id",
        "action",
        "channel",
        "tenant_id",
    ):
        op.drop_index(
            op.f(f"ix_outbound_send_outbox_{column}"),
            table_name=_TABLE,
            schema="public",
        )
    op.drop_table(_TABLE, schema="public")


def _enable_tenant_rls(table_name: str) -> None:
    op.execute(f"ALTER TABLE public.{_q(table_name)} ENABLE ROW LEVEL SECURITY")
    op.execute(f"""
        CREATE POLICY tenant_isolation ON public.{_q(table_name)}
        USING (operious_tenant_rls_allows(tenant_id))
        WITH CHECK (operious_tenant_rls_allows(tenant_id))
        """)
    op.execute(f"ALTER TABLE public.{_q(table_name)} FORCE ROW LEVEL SECURITY")


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


def _q(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'
