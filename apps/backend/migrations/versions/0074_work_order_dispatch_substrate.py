"""work-order dispatch substrate

Revision ID: 0074_work_order_dispatch_substrate
Revises: 0073_tenant_lifecycle
Create Date: 2026-06-05
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0074_work_order_dispatch_substrate"
down_revision: Union[str, None] = "0073_tenant_lifecycle"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "work_order_records"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("work_order_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("proposal_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("execution_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("dispatch_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action_type", sa.String(length=96), nullable=False),
        sa.Column("tool_name", sa.String(length=255), nullable=False),
        sa.Column("connector_type", sa.String(length=255), nullable=False),
        sa.Column("connector_config_version", sa.Integer(), nullable=False),
        sa.Column(
            "connector_config_content_sha256",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "connector_config_source_approval_id",
            sa.String(length=255),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("target_resource", sa.String(length=512), nullable=False),
        sa.Column(
            "state",
            sa.String(length=32),
            server_default=sa.text("'created'"),
            nullable=False,
        ),
        sa.Column(
            "provider_work_order_id",
            sa.String(length=255),
            nullable=True,
        ),
        sa.Column("provider_status", sa.String(length=255), nullable=True),
        sa.Column(
            "last_transition_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
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
        sa.Column(
            "transition_history",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(tenant_id) > 0",
            name=op.f("ck_work_order_records_tenant_id_nonempty"),
        ),
        sa.CheckConstraint(
            "length(action_type) > 0",
            name=op.f("ck_work_order_records_action_type_nonempty"),
        ),
        sa.CheckConstraint(
            "length(tool_name) > 0",
            name=op.f("ck_work_order_records_tool_name_nonempty"),
        ),
        sa.CheckConstraint(
            "length(connector_type) > 0",
            name=op.f("ck_work_order_records_connector_type_nonempty"),
        ),
        sa.CheckConstraint(
            "connector_config_version >= 1",
            name=op.f("ck_work_order_records_connector_config_version_positive"),
        ),
        sa.CheckConstraint(
            "length(connector_config_content_sha256) = 64",
            name=op.f("ck_work_order_records_connector_config_content_sha256_len"),
        ),
        sa.CheckConstraint(
            "length(connector_config_source_approval_id) > 0",
            name=op.f(
                "ck_work_order_records_connector_config_source_approval_id_nonempty"
            ),
        ),
        sa.CheckConstraint(
            "length(idempotency_key) > 0",
            name=op.f("ck_work_order_records_idempotency_key_nonempty"),
        ),
        sa.CheckConstraint(
            "length(target_resource) > 0",
            name=op.f("ck_work_order_records_target_resource_nonempty"),
        ),
        sa.CheckConstraint(
            "state IN ("
            "'created', 'dispatched', 'awaiting_fulfillment', "
            "'fulfilled', 'failed'"
            ")",
            name=op.f("ck_work_order_records_work_order_state_valid"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(transition_history) = 'array'",
            name=op.f("ck_work_order_records_transition_history_array"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(metadata) = 'object'",
            name=op.f("ck_work_order_records_metadata_object"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.tenant_id"],
            name=op.f("fk_work_order_records_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["operational_sessions.session_id"],
            name=op.f("fk_work_order_records_session_id_operational_sessions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["proposal_id"],
            ["resolution_proposals.proposal_id"],
            name=op.f("fk_work_order_records_proposal_id_resolution_proposals"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["execution_id"],
            ["execution_records.execution_id"],
            name=op.f("fk_work_order_records_execution_id_execution_records"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint(
            "work_order_id",
            name=op.f("pk_work_order_records"),
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name=op.f("uq_work_order_records_tenant_idempotency_key"),
        ),
        schema="public",
    )
    op.create_index(
        op.f("ix_work_order_records_tenant_id"),
        _TABLE,
        ["tenant_id"],
        schema="public",
    )
    op.create_index(
        op.f("ix_work_order_records_session_id"),
        _TABLE,
        ["session_id"],
        schema="public",
    )
    op.create_index(
        op.f("ix_work_order_records_proposal_id"),
        _TABLE,
        ["proposal_id"],
        schema="public",
    )
    op.create_index(
        op.f("ix_work_order_records_execution_id"),
        _TABLE,
        ["execution_id"],
        schema="public",
    )
    op.create_index(
        op.f("ix_work_order_records_dispatch_id"),
        _TABLE,
        ["dispatch_id"],
        schema="public",
    )
    op.create_index(
        op.f("ix_work_order_records_action_type"),
        _TABLE,
        ["action_type"],
        schema="public",
    )
    op.create_index(
        op.f("ix_work_order_records_state"),
        _TABLE,
        ["state"],
        schema="public",
    )
    op.create_index(
        op.f("ix_work_order_records_provider_work_order_id"),
        _TABLE,
        ["provider_work_order_id"],
        schema="public",
    )
    op.create_index(
        op.f("ix_work_order_records_tenant_state"),
        _TABLE,
        ["tenant_id", "state"],
        schema="public",
    )
    op.create_index(
        op.f("ix_work_order_records_tenant_action"),
        _TABLE,
        ["tenant_id", "action_type"],
        schema="public",
    )
    op.create_index(
        op.f("ix_work_order_records_tenant_session"),
        _TABLE,
        ["tenant_id", "session_id"],
        schema="public",
    )
    op.create_index(
        op.f("ix_work_order_records_tenant_provider"),
        _TABLE,
        ["tenant_id", "provider_work_order_id"],
        schema="public",
    )
    _enable_tenant_rls(_TABLE)
    _grant_table_if_role("operious_app", _TABLE)
    _grant_table_if_role("operious_app_test", _TABLE)


def downgrade() -> None:
    op.execute(f"ALTER TABLE public.{_q(_TABLE)} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON public.{_q(_TABLE)}")
    for index_name in (
        "ix_work_order_records_tenant_provider",
        "ix_work_order_records_tenant_session",
        "ix_work_order_records_tenant_action",
        "ix_work_order_records_tenant_state",
        "ix_work_order_records_provider_work_order_id",
        "ix_work_order_records_state",
        "ix_work_order_records_action_type",
        "ix_work_order_records_dispatch_id",
        "ix_work_order_records_execution_id",
        "ix_work_order_records_proposal_id",
        "ix_work_order_records_session_id",
        "ix_work_order_records_tenant_id",
    ):
        op.drop_index(op.f(index_name), table_name=_TABLE, schema="public")
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
