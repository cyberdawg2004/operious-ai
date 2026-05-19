"""create supervisor tables (PR-B6)

Four tables backing the Postgres BaseSupervisorRepository
implementation:

* supervisor_inspections   — apex.
* supervisor_findings      — N:1 with inspections.
* supervisor_evaluations   — N:1 with inspections; composite PK
                              (inspection_id, evaluator_name).
* supervisor_escalations   — N:1 with inspections.

Doctrine: nullable tenant_id on apex; sub-records inherit tenant
scope via parent FK. RESTRICT FKs so an apex inspection can never
be silently orphaned. JSONB for the embedded SupervisorDecisionRecord
on the apex, EvaluationEvidenceRecord on each finding, and every
metadata bag.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_supervisor"
down_revision: Union[str, None] = "0008_arbitration"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "supervisor_inspections",
        sa.Column(
            "inspection_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "execution_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "runtime_instance_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "correlation_id", sa.String(length=255), nullable=True
        ),
        sa.Column("request_id", sa.String(length=255), nullable=True),
        sa.Column("tenant_id", sa.String(length=255), nullable=True),
        sa.Column(
            "tenant_authority_source",
            sa.String(length=64),
            nullable=True,
        ),
        sa.Column(
            "inspection_mode", sa.String(length=64), nullable=False
        ),
        sa.Column(
            "decision",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "decision_kind", sa.String(length=64), nullable=False
        ),
        sa.Column(
            "evaluator_names",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "ended_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("latency_ms", sa.Float(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.PrimaryKeyConstraint(
            "inspection_id", name=op.f("pk_supervisor_inspections")
        ),
    )
    for col in (
        "execution_id",
        "runtime_instance_id",
        "correlation_id",
        "request_id",
        "tenant_id",
        "inspection_mode",
        "decision_kind",
        "started_at",
    ):
        op.create_index(
            op.f(f"ix_supervisor_inspections_{col}"),
            "supervisor_inspections",
            [col],
        )

    op.create_table(
        "supervisor_findings",
        sa.Column(
            "finding_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "inspection_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "evaluator_name", sa.String(length=255), nullable=False
        ),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=64), nullable=False),
        sa.Column("code", sa.String(length=255), nullable=False),
        sa.Column(
            "message",
            sa.Text(),
            nullable=False,
            server_default=sa.text("''"),
        ),
        sa.Column(
            "evidence",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "detected_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.ForeignKeyConstraint(
            ["inspection_id"],
            ["supervisor_inspections.inspection_id"],
            name=op.f(
                "fk_supervisor_findings_inspection_id_supervisor_inspections"
            ),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "finding_id", name=op.f("pk_supervisor_findings")
        ),
    )
    op.create_index(
        op.f("ix_supervisor_findings_inspection_id"),
        "supervisor_findings",
        ["inspection_id"],
    )
    op.create_index(
        op.f("ix_supervisor_findings_severity"),
        "supervisor_findings",
        ["severity"],
    )
    op.create_index(
        op.f("ix_supervisor_findings_code"),
        "supervisor_findings",
        ["code"],
    )

    op.create_table(
        "supervisor_evaluations",
        sa.Column(
            "inspection_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "evaluator_name", sa.String(length=255), nullable=False
        ),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column(
            "finding_ids",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "ended_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("latency_ms", sa.Float(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.ForeignKeyConstraint(
            ["inspection_id"],
            ["supervisor_inspections.inspection_id"],
            name=op.f(
                "fk_supervisor_evaluations_inspection_id_supervisor_inspections"
            ),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "inspection_id",
            "evaluator_name",
            name=op.f("pk_supervisor_evaluations"),
        ),
    )

    op.create_table(
        "supervisor_escalations",
        sa.Column(
            "escalation_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "inspection_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "decision_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("level", sa.String(length=64), nullable=False),
        sa.Column(
            "reason",
            sa.Text(),
            nullable=False,
            server_default=sa.text("''"),
        ),
        sa.Column(
            "triggering_finding_ids",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "decided_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.ForeignKeyConstraint(
            ["inspection_id"],
            ["supervisor_inspections.inspection_id"],
            name=op.f(
                "fk_supervisor_escalations_inspection_id_supervisor_inspections"
            ),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "escalation_id",
            name=op.f("pk_supervisor_escalations"),
        ),
        sa.UniqueConstraint(
            "inspection_id",
            "escalation_id",
            name="uq_supervisor_escalations_inspection_escalation",
        ),
    )
    op.create_index(
        op.f("ix_supervisor_escalations_inspection_id"),
        "supervisor_escalations",
        ["inspection_id"],
    )
    op.create_index(
        op.f("ix_supervisor_escalations_decision_id"),
        "supervisor_escalations",
        ["decision_id"],
    )
    op.create_index(
        op.f("ix_supervisor_escalations_level"),
        "supervisor_escalations",
        ["level"],
    )


def downgrade() -> None:
    op.drop_table("supervisor_escalations")
    op.drop_table("supervisor_evaluations")
    op.drop_table("supervisor_findings")
    op.drop_table("supervisor_inspections")
