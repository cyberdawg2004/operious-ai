"""cognition audit records (Phase G)

Revision ID: 0030_cognition_audit_records
Revises: 0029_escalation_outbox
Create Date: 2026-05-23 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0030_cognition_audit_records"
down_revision: Union[str, None] = "0029_escalation_outbox"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "cognition_audit_records",
        sa.Column("audit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("execution_id", sa.String(length=255), nullable=False),
        sa.Column("usage_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("prompt_full", sa.LargeBinary(), nullable=False),
        sa.Column("completion_full", sa.LargeBinary(), nullable=False),
        sa.Column("prompt_sha256", sa.String(length=64), nullable=False),
        sa.Column("completion_sha256", sa.String(length=64), nullable=False),
        sa.Column("model_name", sa.String(length=255), nullable=False),
        sa.Column(
            "token_usage",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "captured_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(tenant_id) > 0",
            name=op.f("ck_cognition_audit_records_tenant_id_nonempty"),
        ),
        sa.CheckConstraint(
            "length(execution_id) > 0",
            name=op.f("ck_cognition_audit_records_execution_id_nonempty"),
        ),
        sa.CheckConstraint(
            "length(model_name) > 0",
            name=op.f("ck_cognition_audit_records_model_name_nonempty"),
        ),
        sa.CheckConstraint(
            "length(prompt_sha256) = 64",
            name=op.f("ck_cognition_audit_records_prompt_sha256_width"),
        ),
        sa.CheckConstraint(
            "length(completion_sha256) = 64",
            name=op.f("ck_cognition_audit_records_completion_sha256_width"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.tenant_id"],
            name=op.f("fk_cognition_audit_records_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "audit_id",
            name=op.f("pk_cognition_audit_records"),
        ),
    )
    op.create_index(
        op.f("ix_cognition_audit_records_tenant_id"),
        "cognition_audit_records",
        ["tenant_id"],
    )
    op.create_index(
        op.f("ix_cognition_audit_records_usage_id"),
        "cognition_audit_records",
        ["usage_id"],
    )
    op.create_index(
        op.f("ix_cognition_audit_records_prompt_sha256"),
        "cognition_audit_records",
        ["prompt_sha256"],
    )
    op.create_index(
        op.f("ix_cognition_audit_records_completion_sha256"),
        "cognition_audit_records",
        ["completion_sha256"],
    )
    op.create_index(
        "ix_cognition_audit_records_tenant_execution",
        "cognition_audit_records",
        ["tenant_id", "execution_id"],
    )
    op.execute("ALTER TABLE cognition_audit_records ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON cognition_audit_records
        USING (operious_tenant_rls_allows(tenant_id))
        WITH CHECK (operious_tenant_rls_allows(tenant_id))
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON cognition_audit_records")
    op.drop_table("cognition_audit_records")
