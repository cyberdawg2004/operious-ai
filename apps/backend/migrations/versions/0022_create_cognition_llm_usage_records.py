"""create cognition LLM usage records (Phase 5-C)

Revision ID: 0022_cognition_llm_usage
Revises: 0021_tenant_knowledge_versions
Create Date: 2026-05-22 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0022_cognition_llm_usage"
down_revision: Union[str, None] = "0021_tenant_knowledge_versions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "cognition_llm_usage_records",
        sa.Column("usage_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("execution_id", sa.String(length=255), nullable=False),
        sa.Column("dispatch_id", sa.String(length=255), nullable=False),
        sa.Column("session_id", sa.String(length=255), nullable=False),
        sa.Column("provider", sa.String(length=255), nullable=False),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("estimated_cost_micro_usd", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(tenant_id) > 0",
            name=op.f("ck_cognition_llm_usage_records_tenant_id_nonempty"),
        ),
        sa.CheckConstraint(
            "length(execution_id) > 0",
            name=op.f("ck_cognition_llm_usage_records_execution_id_nonempty"),
        ),
        sa.CheckConstraint(
            "length(dispatch_id) > 0",
            name=op.f("ck_cognition_llm_usage_records_dispatch_id_nonempty"),
        ),
        sa.CheckConstraint(
            "length(session_id) > 0",
            name=op.f("ck_cognition_llm_usage_records_session_id_nonempty"),
        ),
        sa.CheckConstraint(
            "length(provider) > 0",
            name=op.f("ck_cognition_llm_usage_records_provider_nonempty"),
        ),
        sa.CheckConstraint(
            "length(model) > 0",
            name=op.f("ck_cognition_llm_usage_records_model_nonempty"),
        ),
        sa.CheckConstraint(
            "prompt_tokens >= 0",
            name=op.f("ck_cognition_llm_usage_records_prompt_tokens_nonnegative"),
        ),
        sa.CheckConstraint(
            "completion_tokens >= 0",
            name=op.f("ck_cognition_llm_usage_records_completion_tokens_nonnegative"),
        ),
        sa.CheckConstraint(
            "total_tokens >= 0",
            name=op.f("ck_cognition_llm_usage_records_total_tokens_nonnegative"),
        ),
        sa.CheckConstraint(
            "estimated_cost_micro_usd >= 0",
            name=op.f(
                "ck_cognition_llm_usage_records_estimated_cost_micro_usd_nonnegative"
            ),
        ),
        sa.CheckConstraint(
            "status IN ('accepted', 'rejected', 'failed')",
            name="ck_cognition_llm_usage_records_status_valid",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.tenant_id"],
            name=op.f("fk_cognition_llm_usage_records_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "usage_id",
            name=op.f("pk_cognition_llm_usage_records"),
        ),
    )
    op.create_index(
        op.f("ix_cognition_llm_usage_records_tenant_id"),
        "cognition_llm_usage_records",
        ["tenant_id"],
    )
    op.create_index(
        op.f("ix_cognition_llm_usage_records_status"),
        "cognition_llm_usage_records",
        ["status"],
    )
    op.create_index(
        "ix_cognition_llm_usage_records_tenant_execution",
        "cognition_llm_usage_records",
        ["tenant_id", "execution_id"],
    )
    op.create_index(
        "ix_cognition_llm_usage_records_tenant_model",
        "cognition_llm_usage_records",
        ["tenant_id", "provider", "model"],
    )


def downgrade() -> None:
    op.drop_table("cognition_llm_usage_records")
