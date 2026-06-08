"""email customer reply delivery ledger and sns topic resolver

Revision ID: 0080_email_customer_reply_deliveries
Revises: 0079_whatsapp_customer_reply_deliveries
Create Date: 2026-06-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0080_email_customer_reply_deliveries"
down_revision: str | None = "0079_whatsapp_customer_reply_deliveries"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "email_customer_reply_deliveries"


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
        sa.Column("source_email_address", sa.String(length=255), nullable=False),
        sa.Column("recipient_email_address", sa.String(length=255), nullable=False),
        sa.Column("draft_body_sha256", sa.String(length=64), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("in_reply_to_message_id", sa.String(length=1020), nullable=True),
        sa.Column("references_header", sa.Text(), nullable=True),
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
            name=op.f("ck_email_customer_reply_deliveries_tenant_id_nonempty"),
        ),
        sa.CheckConstraint(
            "length(source_email_address) > 0",
            name=op.f("ck_email_customer_reply_deliveries_source_nonempty"),
        ),
        sa.CheckConstraint(
            "length(recipient_email_address) > 0",
            name=op.f("ck_email_customer_reply_deliveries_recipient_nonempty"),
        ),
        sa.CheckConstraint(
            "length(draft_body_sha256) = 64",
            name=op.f(
                "ck_email_customer_reply_deliveries_draft_body_sha256_valid"
            ),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'sent', 'failed')",
            name=op.f("ck_email_customer_reply_deliveries_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.tenant_id"],
            name=op.f("fk_email_customer_reply_deliveries_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["draft_id"],
            ["resolution_outbound_drafts.draft_id"],
            name=op.f(
                "fk_email_customer_reply_deliveries_draft_id_resolution_outbound_drafts"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["proposal_id"],
            ["resolution_proposals.proposal_id"],
            name=op.f(
                "fk_email_customer_reply_deliveries_proposal_id_resolution_proposals"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["governance_decision_id"],
            ["governance_decisions.decision_id"],
            name=op.f(
                "fk_email_customer_reply_deliveries_governance_decision_id_governance_decisions"
            ),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "delivery_id",
            name=op.f("pk_email_customer_reply_deliveries"),
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "draft_id",
            "governance_decision_id",
            name="uq_email_delivery_tenant_draft_governance",
        ),
        schema="public",
    )
    for column in (
        "tenant_id",
        "draft_id",
        "proposal_id",
        "governance_decision_id",
        "source_email_address",
        "recipient_email_address",
        "status",
        "provider_message_id",
    ):
        op.create_index(
            op.f(f"ix_email_customer_reply_deliveries_{column}"),
            _TABLE,
            [column],
            schema="public",
        )
    op.create_index(
        "ix_email_delivery_tenant_status",
        _TABLE,
        ["tenant_id", "status"],
        schema="public",
    )
    op.create_index(
        "ix_email_delivery_tenant_recipient",
        _TABLE,
        ["tenant_id", "recipient_email_address"],
        schema="public",
    )
    op.create_index(
        "uq_email_delivery_tenant_provider_message",
        _TABLE,
        ["tenant_id", "provider_message_id"],
        schema="public",
        unique=True,
        postgresql_where=sa.text("provider_message_id IS NOT NULL"),
    )
    _enable_tenant_rls(_TABLE)
    _grant_table_if_role("operious_app", _TABLE)
    _grant_table_if_role("operious_app_test", _TABLE)
    _create_sns_topic_resolver()


def downgrade() -> None:
    op.execute(
        "DROP FUNCTION IF EXISTS "
        "public.resolve_webhook_routing_secret_by_topic_arn(text, text)"
    )
    op.execute(f"ALTER TABLE public.{_q(_TABLE)} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON public.{_q(_TABLE)}")
    op.drop_index(
        "uq_email_delivery_tenant_provider_message",
        table_name=_TABLE,
        schema="public",
    )
    op.drop_index(
        "ix_email_delivery_tenant_recipient",
        table_name=_TABLE,
        schema="public",
    )
    op.drop_index(
        "ix_email_delivery_tenant_status",
        table_name=_TABLE,
        schema="public",
    )
    for column in (
        "provider_message_id",
        "status",
        "recipient_email_address",
        "source_email_address",
        "governance_decision_id",
        "proposal_id",
        "draft_id",
        "tenant_id",
    ):
        op.drop_index(
            op.f(f"ix_email_customer_reply_deliveries_{column}"),
            table_name=_TABLE,
            schema="public",
        )
    op.drop_table(_TABLE, schema="public")


def _create_sns_topic_resolver() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.resolve_webhook_routing_secret_by_topic_arn(
            p_channel_type text,
            p_topic_arn text
        )
        RETURNS TABLE (
            tenant_id text,
            config_id uuid,
            channel_type text,
            routing_address text,
            webhook_secret text,
            previous_webhook_secret text,
            credential_rotation_expires_at timestamptz
        )
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
            WITH matches AS (
                SELECT
                    tcc.tenant_id::text,
                    tcc.config_id,
                    tcc.channel_type::text,
                    tcc.routing_address::text,
                    tcc.webhook_secret::text,
                    tcc.previous_webhook_secret::text,
                    tcc.credential_rotation_expires_at
                FROM public.tenant_channel_configurations tcc
                WHERE tcc.channel_type = p_channel_type
                  AND tcc.status = 'active'
                  AND (
                    tcc.webhook_secret = p_topic_arn
                    OR (
                        tcc.previous_webhook_secret = p_topic_arn
                        AND tcc.credential_rotation_expires_at > now()
                    )
                  )
                LIMIT 2
            ),
            counted AS (
                SELECT COUNT(*) AS match_count FROM matches
            )
            SELECT
                matches.tenant_id,
                matches.config_id,
                matches.channel_type,
                matches.routing_address,
                matches.webhook_secret,
                matches.previous_webhook_secret,
                matches.credential_rotation_expires_at
            FROM matches, counted
            WHERE counted.match_count = 1
        $$;
        """
    )
    _alter_owner_if_neon("resolve_webhook_routing_secret_by_topic_arn(text, text)")
    op.execute(
        "REVOKE ALL ON FUNCTION "
        "public.resolve_webhook_routing_secret_by_topic_arn(text, text) FROM PUBLIC"
    )
    _grant_execute_if_role(
        "resolve_webhook_routing_secret_by_topic_arn(text, text)",
        "operious_app",
    )
    _grant_execute_if_role(
        "resolve_webhook_routing_secret_by_topic_arn(text, text)",
        "operious_app_test",
    )


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


def _grant_execute_if_role(signature: str, role_name: str) -> None:
    escaped_signature = signature.replace("'", "''")
    escaped_role = role_name.replace("'", "''")
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT FROM pg_roles WHERE rolname = '{escaped_role}'
            ) THEN
                EXECUTE format(
                    'GRANT EXECUTE ON FUNCTION public.{escaped_signature} TO %I',
                    '{escaped_role}'
                );
            END IF;
        END
        $$;
        """
    )


def _alter_owner_if_neon(signature: str) -> None:
    escaped = signature.replace("'", "''")
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT FROM pg_roles WHERE rolname = 'neondb_owner'
            ) THEN
                EXECUTE 'ALTER FUNCTION public.{escaped} OWNER TO neondb_owner';
            END IF;
        END
        $$;
        """
    )


def _q(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'
