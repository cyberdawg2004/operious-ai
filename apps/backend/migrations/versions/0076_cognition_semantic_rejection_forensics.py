"""persist semantic rejection forensics

Revision ID: 0076_cognition_semantic_rejection_forensics
Revises: 0075_knowledge_embeddings_1536
Create Date: 2026-06-06
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0076_cognition_semantic_rejection_forensics"
down_revision: Union[str, None] = "0075_knowledge_embeddings_1536"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "cognition_semantic_rejection_records"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("rejection_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("execution_id", sa.String(length=255), nullable=False),
        sa.Column("dispatch_id", sa.String(length=255), nullable=False),
        sa.Column("session_id", sa.String(length=255), nullable=False),
        sa.Column("attempt_id", sa.String(length=255), nullable=True),
        sa.Column("attempt_number", sa.Integer(), nullable=True),
        sa.Column("usage_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("audit_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("provider", sa.String(length=255), nullable=False),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column(
            "canonical_terms",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "allowed_terms",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "output_terms",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "missing_terms",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "introduced_terms",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("direction", sa.String(length=32), nullable=False),
        sa.Column("completion_sha256", sa.String(length=64), nullable=False),
        sa.Column("completion_excerpt", sa.Text(), nullable=False),
        sa.Column("completion_excerpt_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
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
            name=op.f("ck_cognition_semantic_rejection_records_tenant_id_nonempty"),
        ),
        sa.CheckConstraint(
            "length(execution_id) > 0",
            name=op.f("ck_cognition_semantic_rejection_records_execution_id_nonempty"),
        ),
        sa.CheckConstraint(
            "length(dispatch_id) > 0",
            name=op.f("ck_cognition_semantic_rejection_records_dispatch_id_nonempty"),
        ),
        sa.CheckConstraint(
            "length(session_id) > 0",
            name=op.f("ck_cognition_semantic_rejection_records_session_id_nonempty"),
        ),
        sa.CheckConstraint(
            "length(provider) > 0",
            name=op.f("ck_cognition_semantic_rejection_records_provider_nonempty"),
        ),
        sa.CheckConstraint(
            "length(model) > 0",
            name=op.f("ck_cognition_semantic_rejection_records_model_nonempty"),
        ),
        sa.CheckConstraint(
            "direction IN ('DROP', 'INTRODUCE', 'DROP_AND_INTRODUCE', 'NONE')",
            name=op.f(
                "ck_cognition_semantic_rejection_records_direction_valid"
            ),
        ),
        sa.CheckConstraint(
            "length(completion_sha256) = 64",
            name=op.f(
                "ck_cognition_semantic_rejection_records_completion_sha256_width"
            ),
        ),
        sa.CheckConstraint(
            "length(completion_excerpt_sha256) = 64",
            name=op.f(
                "ck_cognition_semantic_rejection_records_excerpt_sha256_width"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.tenant_id"],
            name=op.f("fk_cognition_semantic_rejection_records_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "rejection_id",
            name=op.f("pk_cognition_semantic_rejection_records"),
        ),
        schema="public",
    )
    op.create_index(
        op.f("ix_cognition_semantic_rejection_records_tenant_id"),
        _TABLE,
        ["tenant_id"],
        schema="public",
    )
    op.create_index(
        op.f("ix_cognition_semantic_rejection_records_usage_id"),
        _TABLE,
        ["usage_id"],
        schema="public",
    )
    op.create_index(
        op.f("ix_cognition_semantic_rejection_records_audit_id"),
        _TABLE,
        ["audit_id"],
        schema="public",
    )
    op.create_index(
        op.f("ix_cognition_semantic_rejection_records_direction"),
        _TABLE,
        ["direction"],
        schema="public",
    )
    op.create_index(
        op.f("ix_cognition_semantic_rejection_records_completion_sha256"),
        _TABLE,
        ["completion_sha256"],
        schema="public",
    )
    op.create_index(
        "ix_cognition_semantic_rejection_tenant_execution",
        _TABLE,
        ["tenant_id", "execution_id"],
        schema="public",
    )
    op.create_index(
        "ix_cognition_semantic_rejection_tenant_created",
        _TABLE,
        ["tenant_id", "created_at"],
        schema="public",
    )
    op.execute(f"ALTER TABLE public.{_TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE public.{_TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY tenant_isolation ON public.{_TABLE}
        USING (operious_tenant_rls_allows(tenant_id))
        WITH CHECK (operious_tenant_rls_allows(tenant_id))
        """
    )
    _grant_table_if_role("operious_app", _TABLE)
    _grant_table_if_role("operious_app_test", _TABLE)


def downgrade() -> None:
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON public.{_TABLE}")
    op.drop_table(_TABLE, schema="public")


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
