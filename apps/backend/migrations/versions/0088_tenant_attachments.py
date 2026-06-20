"""tenant_attachments — customer evidence storage foundation (Phase B1a)

Revision ID: 0088_tenant_attachments
Revises: 0087_connector_configs_force_rls
Create Date: 2026-06-20

Metadata-only table: binaries live in S3 (see app.attachments.s3_client),
encrypted via the same app-layer envelope used by tenant_knowledge_uploads
(app.data_protection.crypto.DataProtectionService, tenant_scoped=True).
This table holds only the storage reference + sniffed/declared content
type + status, under the same ENABLE/FORCE RLS + operious_tenant_rls_allows
policy as migration 0070, so the generic RLS-coverage invariant
(tests/test_rls_coverage_invariant.py) covers it automatically.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0088_tenant_attachments"
down_revision: Union[str, None] = "0087_connector_configs_force_rls"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "tenant_attachments"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("attachment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("external_message_id", sa.String(length=255), nullable=True),
        sa.Column("conversation_id", sa.String(length=255), nullable=True),
        sa.Column(
            "storage_backend",
            sa.String(length=16),
            server_default=sa.text("'s3'"),
            nullable=False,
        ),
        sa.Column("storage_key", sa.String(length=512), nullable=True),
        sa.Column("content_type_declared", sa.String(length=128), nullable=True),
        sa.Column("content_type_sniffed", sa.String(length=128), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256_digest", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("retention_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "length(tenant_id) > 0",
            name=op.f("ck_tenant_attachments_tenant_id_nonempty"),
        ),
        sa.CheckConstraint(
            "size_bytes >= 0",
            name=op.f("ck_tenant_attachments_size_bytes_nonnegative"),
        ),
        sa.CheckConstraint(
            "channel IN ('email', 'whatsapp')",
            name=op.f("ck_tenant_attachments_channel_valid"),
        ),
        sa.CheckConstraint(
            "storage_backend IN ('s3', 'postgres')",
            name=op.f("ck_tenant_attachments_storage_backend_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('stored', 'rejected')",
            name=op.f("ck_tenant_attachments_status_valid"),
        ),
        sa.CheckConstraint(
            "(status = 'stored' AND storage_key IS NOT NULL) "
            "OR (status = 'rejected' AND storage_key IS NULL)",
            name=op.f("ck_tenant_attachments_storage_key_matches_status"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.tenant_id"],
            name=op.f("fk_tenant_attachments_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("attachment_id", name=op.f("pk_tenant_attachments")),
        schema="public",
    )
    op.create_index(
        op.f("ix_tenant_attachments_tenant_status"),
        _TABLE,
        ["tenant_id", "status"],
        schema="public",
    )
    op.create_index(
        op.f("ix_tenant_attachments_tenant_message"),
        _TABLE,
        ["tenant_id", "external_message_id"],
        schema="public",
    )
    _enable_tenant_rls(_TABLE)
    _grant_table_if_role("operious_app", _TABLE)
    _grant_table_if_role("operious_app_test", _TABLE)


def downgrade() -> None:
    op.execute(f"ALTER TABLE public.{_q(_TABLE)} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON public.{_q(_TABLE)}")
    op.drop_index(
        op.f("ix_tenant_attachments_tenant_message"),
        table_name=_TABLE,
        schema="public",
    )
    op.drop_index(
        op.f("ix_tenant_attachments_tenant_status"),
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
