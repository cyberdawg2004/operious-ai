"""create escalation records table (Phase 3-C)

Revision ID: 0017_escalation_records
Revises: 0016_qa_score_records
Create Date: 2026-05-22 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0017_escalation_records"
down_revision: Union[str, None] = "0016_qa_score_records"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "escalation_records",
        sa.Column(
            "escalation_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "governance_decision_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution", sa.Text(), nullable=True),
        sa.Column("resolved_by", sa.String(length=255), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.CheckConstraint(
            "length(tenant_id) > 0",
            name=op.f("ck_escalation_records_tenant_id_nonempty"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'reviewed', 'approved', 'rejected')",
            name=op.f("ck_escalation_records_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["governance_decision_id"],
            ["governance_decisions.decision_id"],
            name=op.f(
                "fk_escalation_records_governance_decision_id_governance_decisions"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["operational_sessions.session_id"],
            name=op.f("fk_escalation_records_session_id_operational_sessions"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "escalation_id", name=op.f("pk_escalation_records")
        ),
        sa.UniqueConstraint(
            "governance_decision_id",
            name="uq_escalation_records_governance_decision_id",
        ),
    )
    for col in (
        "session_id",
        "tenant_id",
        "governance_decision_id",
        "status",
        "created_at",
        "resolved_by",
    ):
        op.create_index(
            op.f(f"ix_escalation_records_{col}"),
            "escalation_records",
            [col],
        )


def downgrade() -> None:
    op.drop_table("escalation_records")
