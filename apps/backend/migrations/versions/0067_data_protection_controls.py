"""data protection envelope keys and retention controls

Revision ID: 0067_data_protection_controls
Revises: 0066_tenant_config_change_request_revocation
Create Date: 2026-06-01
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0067_data_protection_controls"
down_revision: Union[str, None] = "0066_tenant_config_change_request_revocation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_RLS_TABLES: tuple[str, ...] = (
    "data_protection_data_keys",
    "tenant_data_retention_policies",
    "data_protection_legal_holds",
    "data_protection_erasure_requests",
)


def upgrade() -> None:
    op.create_table(
        "data_protection_data_keys",
        sa.Column("data_key_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("scope_id", sa.String(length=255), nullable=False),
        sa.Column("master_key_version", sa.String(length=255), nullable=False),
        sa.Column("encrypted_key", sa.LargeBinary(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("rewrapped_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "length(tenant_id) > 0",
            name=op.f("ck_data_protection_data_keys_data_key_tenant_nonempty"),
        ),
        sa.CheckConstraint(
            "scope IN ('tenant', 'subject')",
            name=op.f("ck_data_protection_data_keys_data_key_scope_valid"),
        ),
        sa.CheckConstraint(
            "length(scope_id) > 0",
            name=op.f("ck_data_protection_data_keys_data_key_scope_id_nonempty"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.tenant_id"],
            ondelete="CASCADE",
            name=op.f("fk_data_protection_data_keys_tenant_id_tenants"),
        ),
        sa.PrimaryKeyConstraint(
            "data_key_id", name=op.f("pk_data_protection_data_keys")
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "scope",
            "scope_id",
            name="uq_data_protection_data_keys_scope",
        ),
        schema="public",
    )
    op.create_index(
        op.f("ix_data_protection_data_keys_tenant_id"),
        "data_protection_data_keys",
        ["tenant_id"],
        schema="public",
    )
    op.create_index(
        op.f("ix_data_protection_data_keys_scope"),
        "data_protection_data_keys",
        ["scope"],
        schema="public",
    )
    op.create_index(
        op.f("ix_data_protection_data_keys_master_key_version"),
        "data_protection_data_keys",
        ["master_key_version"],
        schema="public",
    )
    op.create_index(
        "ix_data_protection_data_keys_tenant_scope",
        "data_protection_data_keys",
        ["tenant_id", "scope", "scope_id"],
        schema="public",
    )

    op.create_table(
        "tenant_data_retention_policies",
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column(
            "retention_days",
            sa.Integer(),
            server_default=sa.text("90"),
            nullable=False,
        ),
        sa.Column("updated_by", sa.String(length=255), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(tenant_id) > 0",
            name=op.f(
                "ck_tenant_data_retention_policies_retention_tenant_nonempty"
            ),
        ),
        sa.CheckConstraint(
            "retention_days >= 1",
            name=op.f("ck_tenant_data_retention_policies_retention_days_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.tenant_id"],
            ondelete="CASCADE",
            name=op.f("fk_tenant_data_retention_policies_tenant_id_tenants"),
        ),
        sa.PrimaryKeyConstraint(
            "tenant_id", name=op.f("pk_tenant_data_retention_policies")
        ),
        schema="public",
    )

    op.create_table(
        "data_protection_legal_holds",
        sa.Column("hold_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("scope_id", sa.String(length=255), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("lifted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lifted_by", sa.String(length=255), nullable=True),
        sa.CheckConstraint(
            "length(tenant_id) > 0",
            name=op.f(
                "ck_data_protection_legal_holds_legal_hold_tenant_nonempty"
            ),
        ),
        sa.CheckConstraint(
            "scope IN ('tenant', 'subject', 'session')",
            name=op.f("ck_data_protection_legal_holds_legal_hold_scope_valid"),
        ),
        sa.CheckConstraint(
            "length(scope_id) > 0",
            name=op.f(
                "ck_data_protection_legal_holds_legal_hold_scope_id_nonempty"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.tenant_id"],
            ondelete="RESTRICT",
            name=op.f("fk_data_protection_legal_holds_tenant_id_tenants"),
        ),
        sa.PrimaryKeyConstraint(
            "hold_id", name=op.f("pk_data_protection_legal_holds")
        ),
        schema="public",
    )
    op.create_index(
        op.f("ix_data_protection_legal_holds_tenant_id"),
        "data_protection_legal_holds",
        ["tenant_id"],
        schema="public",
    )
    op.create_index(
        op.f("ix_data_protection_legal_holds_scope"),
        "data_protection_legal_holds",
        ["scope"],
        schema="public",
    )
    op.create_index(
        "ix_data_protection_legal_holds_active_scope",
        "data_protection_legal_holds",
        ["tenant_id", "scope", "scope_id"],
        unique=False,
        postgresql_where=sa.text("lifted_at IS NULL"),
        schema="public",
    )

    op.create_table(
        "data_protection_erasure_requests",
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("subject_id", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("requested_by", sa.String(length=255), nullable=False),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("blocked_reason", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "length(tenant_id) > 0",
            name=op.f(
                "ck_data_protection_erasure_requests_erasure_tenant_nonempty"
            ),
        ),
        sa.CheckConstraint(
            "length(subject_id) > 0",
            name=op.f(
                "ck_data_protection_erasure_requests_erasure_subject_nonempty"
            ),
        ),
        sa.CheckConstraint(
            "status IN ('completed', 'blocked')",
            name=op.f("ck_data_protection_erasure_requests_erasure_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.tenant_id"],
            ondelete="RESTRICT",
            name=op.f("fk_data_protection_erasure_requests_tenant_id_tenants"),
        ),
        sa.PrimaryKeyConstraint(
            "request_id", name=op.f("pk_data_protection_erasure_requests")
        ),
        schema="public",
    )
    op.create_index(
        op.f("ix_data_protection_erasure_requests_tenant_id"),
        "data_protection_erasure_requests",
        ["tenant_id"],
        schema="public",
    )
    op.create_index(
        op.f("ix_data_protection_erasure_requests_status"),
        "data_protection_erasure_requests",
        ["status"],
        schema="public",
    )
    op.create_index(
        "ix_data_protection_erasure_requests_subject",
        "data_protection_erasure_requests",
        ["tenant_id", "subject_id", "requested_at"],
        schema="public",
    )

    for table_name in _RLS_TABLES:
        _enable_tenant_rls(table_name)
        _grant_table_if_role("operious_app", table_name)
        _grant_table_if_role("operious_app_test", table_name)


def downgrade() -> None:
    for table_name in reversed(_RLS_TABLES):
        op.execute(f"ALTER TABLE public.{_q(table_name)} NO FORCE ROW LEVEL SECURITY")
        op.execute(
            f"DROP POLICY IF EXISTS tenant_isolation ON public.{_q(table_name)}"
        )
        op.execute(f"ALTER TABLE public.{_q(table_name)} DISABLE ROW LEVEL SECURITY")

    op.drop_index(
        "ix_data_protection_erasure_requests_subject",
        table_name="data_protection_erasure_requests",
        schema="public",
    )
    op.drop_index(
        op.f("ix_data_protection_erasure_requests_status"),
        table_name="data_protection_erasure_requests",
        schema="public",
    )
    op.drop_index(
        op.f("ix_data_protection_erasure_requests_tenant_id"),
        table_name="data_protection_erasure_requests",
        schema="public",
    )
    op.drop_table("data_protection_erasure_requests", schema="public")

    op.drop_index(
        "ix_data_protection_legal_holds_active_scope",
        table_name="data_protection_legal_holds",
        schema="public",
    )
    op.drop_index(
        op.f("ix_data_protection_legal_holds_scope"),
        table_name="data_protection_legal_holds",
        schema="public",
    )
    op.drop_index(
        op.f("ix_data_protection_legal_holds_tenant_id"),
        table_name="data_protection_legal_holds",
        schema="public",
    )
    op.drop_table("data_protection_legal_holds", schema="public")
    op.drop_table("tenant_data_retention_policies", schema="public")

    op.drop_index(
        "ix_data_protection_data_keys_tenant_scope",
        table_name="data_protection_data_keys",
        schema="public",
    )
    op.drop_index(
        op.f("ix_data_protection_data_keys_master_key_version"),
        table_name="data_protection_data_keys",
        schema="public",
    )
    op.drop_index(
        op.f("ix_data_protection_data_keys_scope"),
        table_name="data_protection_data_keys",
        schema="public",
    )
    op.drop_index(
        op.f("ix_data_protection_data_keys_tenant_id"),
        table_name="data_protection_data_keys",
        schema="public",
    )
    op.drop_table("data_protection_data_keys", schema="public")


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
                    'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.%I TO %I',
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
