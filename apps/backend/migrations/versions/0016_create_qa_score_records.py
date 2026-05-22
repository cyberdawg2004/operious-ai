"""create QA score records table (Phase 3-B)

Revision ID: 0016_qa_score_records
Revises: 0015_boundary_idempotency
Create Date: 2026-05-22 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016_qa_score_records"
down_revision: Union[str, None] = "0015_boundary_idempotency"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "qa_score_records",
        sa.Column("score_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "inspection_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column(
            "execution_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column(
            "tenant_authority_source",
            sa.String(length=64),
            nullable=True,
        ),
        sa.Column("diagnostic_accuracy", sa.Float(), nullable=False),
        sa.Column("policy_compliance", sa.Float(), nullable=False),
        sa.Column("timeline_integrity", sa.Float(), nullable=False),
        sa.Column("resolution_quality", sa.Float(), nullable=False),
        sa.Column("overall_score", sa.Float(), nullable=False),
        sa.Column(
            "supervisor_decision_kind",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column("finding_count", sa.Integer(), nullable=False),
        sa.Column("evaluation_count", sa.Integer(), nullable=False),
        sa.Column("escalation_count", sa.Integer(), nullable=False),
        sa.Column("scored_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.CheckConstraint(
            "length(tenant_id) > 0",
            name=op.f("ck_qa_score_records_tenant_id_nonempty"),
        ),
        sa.CheckConstraint(
            "diagnostic_accuracy >= 0 AND diagnostic_accuracy <= 1",
            name=op.f("ck_qa_score_records_diagnostic_accuracy_bounds"),
        ),
        sa.CheckConstraint(
            "policy_compliance >= 0 AND policy_compliance <= 1",
            name=op.f("ck_qa_score_records_policy_compliance_bounds"),
        ),
        sa.CheckConstraint(
            "timeline_integrity >= 0 AND timeline_integrity <= 1",
            name=op.f("ck_qa_score_records_timeline_integrity_bounds"),
        ),
        sa.CheckConstraint(
            "resolution_quality >= 0 AND resolution_quality <= 1",
            name=op.f("ck_qa_score_records_resolution_quality_bounds"),
        ),
        sa.CheckConstraint(
            "overall_score >= 0 AND overall_score <= 1",
            name=op.f("ck_qa_score_records_overall_score_bounds"),
        ),
        sa.ForeignKeyConstraint(
            ["inspection_id"],
            ["supervisor_inspections.inspection_id"],
            name=op.f(
                "fk_qa_score_records_inspection_id_supervisor_inspections"
            ),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "score_id", name=op.f("pk_qa_score_records")
        ),
        sa.UniqueConstraint(
            "inspection_id",
            name="uq_qa_score_records_inspection_id",
        ),
    )
    for col in (
        "inspection_id",
        "execution_id",
        "tenant_id",
        "supervisor_decision_kind",
        "scored_at",
    ):
        op.create_index(
            op.f(f"ix_qa_score_records_{col}"),
            "qa_score_records",
            [col],
        )


def downgrade() -> None:
    op.drop_table("qa_score_records")
