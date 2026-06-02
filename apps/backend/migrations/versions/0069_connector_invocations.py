"""connector invocation idempotency ledger

Revision ID: 0069_connector_invocations
Revises: 0068_erasure_dual_control
Create Date: 2026-06-03
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0069_connector_invocations"
down_revision: Union[str, None] = "0068_erasure_dual_control"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "connector_invocations"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("provider_idempotency_key", sa.String(length=64), nullable=False),
        sa.Column("connector_type", sa.String(length=255), nullable=False),
        sa.Column("action_type", sa.String(length=96), nullable=False),
        sa.Column("target_resource", sa.String(length=512), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("provider_id", sa.String(length=255), nullable=True),
        sa.Column("provider_status", sa.String(length=255), nullable=True),
        sa.Column("provider_error", sa.Text(), nullable=True),
        sa.Column(
            "attempt",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column("governance_decision_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "length(tenant_id) > 0",
            name=op.f("ck_connector_invocations_tenant_id_nonempty"),
        ),
        sa.CheckConstraint(
            "length(provider_idempotency_key) > 0",
            name=op.f("ck_connector_invocations_provider_key_nonempty"),
        ),
        sa.CheckConstraint(
            "length(connector_type) > 0",
            name=op.f("ck_connector_invocations_connector_type_nonempty"),
        ),
        sa.CheckConstraint(
            "length(action_type) > 0",
            name=op.f("ck_connector_invocations_action_type_nonempty"),
        ),
        sa.CheckConstraint(
            "length(target_resource) > 0",
            name=op.f("ck_connector_invocations_target_resource_nonempty"),
        ),
        sa.CheckConstraint(
            "length(request_hash) = 64",
            name=op.f("ck_connector_invocations_request_hash_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'succeeded', 'failed')",
            name=op.f("ck_connector_invocations_status_valid"),
        ),
        sa.CheckConstraint(
            "attempt >= 1",
            name=op.f("ck_connector_invocations_attempt_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.tenant_id"],
            name=op.f("fk_connector_invocations_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["governance_decision_id"],
            ["governance_decisions.decision_id"],
            name=op.f(
                "fk_connector_invocations_governance_decision_id_governance_decisions"
            ),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint(
            "tenant_id",
            "provider_idempotency_key",
            name=op.f("pk_connector_invocations"),
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "provider_idempotency_key",
            name=op.f("uq_connector_invocations_tenant_provider_key"),
        ),
        schema="public",
    )
    op.create_index(
        op.f("ix_connector_invocations_tenant_status"),
        _TABLE,
        ["tenant_id", "status"],
        schema="public",
    )
    op.create_index(
        op.f("ix_connector_invocations_tenant_governance"),
        _TABLE,
        ["tenant_id", "governance_decision_id"],
        schema="public",
    )
    _enable_tenant_rls(_TABLE)
    _grant_table_if_role("operious_app", _TABLE)
    _grant_table_if_role("operious_app_test", _TABLE)


def downgrade() -> None:
    op.execute(f"ALTER TABLE public.{_q(_TABLE)} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON public.{_q(_TABLE)}")
    op.drop_index(
        op.f("ix_connector_invocations_tenant_governance"),
        table_name=_TABLE,
        schema="public",
    )
    op.drop_index(
        op.f("ix_connector_invocations_tenant_status"),
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
