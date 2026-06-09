"""durable ingress dispatch outbox

Revision ID: 0081_ingress_dispatch_outbox
Revises: 0080_email_customer_reply_deliveries
Create Date: 2026-06-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0081_ingress_dispatch_outbox"
down_revision: str | None = "0080_email_customer_reply_deliveries"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "ingress_dispatch_outbox"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("outbox_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ingress_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("channel", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.String(length=64),
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
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.CheckConstraint(
            "length(tenant_id) > 0",
            name=op.f("ck_ingress_dispatch_outbox_tenant_id_nonempty"),
        ),
        sa.CheckConstraint(
            "channel IN ('email', 'whatsapp', 'shopify')",
            name=op.f("ck_ingress_dispatch_outbox_channel_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'claimed', 'dispatched', 'dead_lettered')",
            name=op.f("ck_ingress_dispatch_outbox_status_valid"),
        ),
        sa.CheckConstraint(
            "attempt_count >= 0",
            name=op.f("ck_ingress_dispatch_outbox_attempt_nonnegative"),
        ),
        sa.ForeignKeyConstraint(
            ["ingress_id"],
            ["boundary_ingress.ingress_id"],
            name=op.f("fk_ingress_dispatch_outbox_ingress_id_boundary_ingress"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "outbox_id",
            name=op.f("pk_ingress_dispatch_outbox"),
        ),
        sa.UniqueConstraint(
            "ingress_id",
            name="uq_ingress_dispatch_outbox_ingress_id",
        ),
        schema="public",
    )
    for column in (
        "ingress_id",
        "tenant_id",
        "channel",
        "status",
        "claim_id",
        "worker_id",
        "next_attempt_at",
        "created_at",
        "claimed_at",
    ):
        op.create_index(
            op.f(f"ix_ingress_dispatch_outbox_{column}"),
            _TABLE,
            [column],
            schema="public",
        )
    op.create_index(
        "ix_ingress_dispatch_outbox_status_next_attempt",
        _TABLE,
        ["status", "next_attempt_at"],
        schema="public",
    )
    op.create_index(
        "ix_ingress_dispatch_outbox_tenant_status",
        _TABLE,
        ["tenant_id", "status"],
        schema="public",
    )
    _enable_tenant_rls(_TABLE)
    _grant_table_if_role("operious_app", _TABLE)
    _grant_table_if_role("operious_app_test", _TABLE)


def downgrade() -> None:
    op.execute(f"ALTER TABLE public.{_q(_TABLE)} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON public.{_q(_TABLE)}")
    op.drop_index(
        "ix_ingress_dispatch_outbox_tenant_status",
        table_name=_TABLE,
        schema="public",
    )
    op.drop_index(
        "ix_ingress_dispatch_outbox_status_next_attempt",
        table_name=_TABLE,
        schema="public",
    )
    for column in (
        "claimed_at",
        "created_at",
        "next_attempt_at",
        "worker_id",
        "claim_id",
        "status",
        "channel",
        "tenant_id",
        "ingress_id",
    ):
        op.drop_index(
            op.f(f"ix_ingress_dispatch_outbox_{column}"),
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
