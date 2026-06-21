"""whatsapp_media_fetch_records — Meta media two-hop fetch ledger (Phase B1.5)

Revision ID: 0089_whatsapp_media_fetch_records
Revises: 0088_tenant_attachments
Create Date: 2026-06-21

The boundary_ingress / coordination_envelopes chain is write-once
end-to-end (lineage NEVER changes) — there is no mutable "ticket" row a
background task could patch once a WhatsApp media id is captured at
webhook time. This table is that mutable side-channel: the webhook
writes a `pending` row immediately (durable, so a media id is never
lost even if the fetch task fails to enqueue); a background task
resolves it to `stored` (with attachment_id) or `failed`; the dispatch
service reads resolved rows by ingress_id to fold the final attachment
state into the coordination envelope at the one point it's still being
written for the first time.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0089_whatsapp_media_fetch_records"
down_revision: Union[str, None] = "0088_tenant_attachments"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "whatsapp_media_fetch_records"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("fetch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("ingress_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("external_message_id", sa.String(length=255), nullable=False),
        sa.Column("media_id", sa.String(length=255), nullable=False),
        sa.Column("mime_type", sa.String(length=128), nullable=True),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("attachment_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "attempt_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "length(tenant_id) > 0",
            name=op.f("ck_whatsapp_media_fetch_records_tenant_id_nonempty"),
        ),
        sa.CheckConstraint(
            "attempt_count >= 0",
            name=op.f("ck_whatsapp_media_fetch_records_attempt_nonnegative"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'stored', 'failed')",
            name=op.f("ck_whatsapp_media_fetch_records_status_valid"),
        ),
        sa.CheckConstraint(
            "(status = 'stored' AND attachment_id IS NOT NULL) "
            "OR (status != 'stored' AND attachment_id IS NULL)",
            name=op.f("ck_whatsapp_media_fetch_records_attachment_matches_status"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.tenant_id"],
            name=op.f("fk_whatsapp_media_fetch_records_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["ingress_id"],
            ["boundary_ingress.ingress_id"],
            name=op.f(
                "fk_whatsapp_media_fetch_records_ingress_id_boundary_ingress"
            ),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("fetch_id", name=op.f("pk_whatsapp_media_fetch_records")),
        sa.UniqueConstraint(
            "tenant_id",
            "ingress_id",
            "media_id",
            name="uq_whatsapp_media_fetch_records_tenant_ingress_media",
        ),
        schema="public",
    )
    op.create_index(
        op.f("ix_whatsapp_media_fetch_records_tenant_status"),
        _TABLE,
        ["tenant_id", "status"],
        schema="public",
    )
    op.create_index(
        op.f("ix_whatsapp_media_fetch_records_ingress_id"),
        _TABLE,
        ["ingress_id"],
        schema="public",
    )
    op.create_index(
        op.f("ix_whatsapp_media_fetch_records_status_created"),
        _TABLE,
        ["status", "created_at"],
        schema="public",
    )
    _enable_tenant_rls(_TABLE)
    _grant_table_if_role("operious_app", _TABLE)
    _grant_table_if_role("operious_app_test", _TABLE)


def downgrade() -> None:
    op.execute(f"ALTER TABLE public.{_q(_TABLE)} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON public.{_q(_TABLE)}")
    op.drop_index(
        op.f("ix_whatsapp_media_fetch_records_status_created"),
        table_name=_TABLE,
        schema="public",
    )
    op.drop_index(
        op.f("ix_whatsapp_media_fetch_records_ingress_id"),
        table_name=_TABLE,
        schema="public",
    )
    op.drop_index(
        op.f("ix_whatsapp_media_fetch_records_tenant_status"),
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
