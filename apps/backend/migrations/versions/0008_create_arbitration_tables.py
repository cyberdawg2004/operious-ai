"""create arbitration tables (PR-B5)

Single table: ``arbitration_evaluations``. Nested findings /
conflicts / deadlock_witnesses live as JSONB arrays on the same
row (the substrate's contract is "one apex evaluation = one row").

Doctrine:
* Nullable tenant_id; no partitioning (low volume).
* Composite (runtime_instance_id, sequence) index for the
  Protocol's canonical ordering.
* JSONB blobs for evaluator_names + every nested record array +
  metadata.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_arbitration"
down_revision: Union[str, None] = "0007_coordination"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "arbitration_evaluations",
        sa.Column(
            "evaluation_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "chain_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "case_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "runtime_instance_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.String(length=64), nullable=False),
        sa.Column(
            "prevailing_authority_level",
            sa.String(length=64),
            nullable=True,
        ),
        sa.Column(
            "prevailing_authority_source_substrate",
            sa.String(length=255),
            nullable=True,
        ),
        sa.Column(
            "prevailing_authority_source_id",
            sa.String(length=255),
            nullable=True,
        ),
        sa.Column(
            "prevailing_authority_verdict",
            sa.String(length=64),
            nullable=True,
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "evaluator_names",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "findings",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "conflicts",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "deadlock_witnesses",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("signal_count", sa.Integer(), nullable=False),
        sa.Column(
            "recommendation_count", sa.Integer(), nullable=False
        ),
        sa.Column("iteration_count", sa.Integer(), nullable=False),
        sa.Column("max_iterations", sa.Integer(), nullable=False),
        sa.Column(
            "correlation_id", sa.String(length=255), nullable=True
        ),
        sa.Column("request_id", sa.String(length=255), nullable=True),
        sa.Column("tenant_id", sa.String(length=255), nullable=True),
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
            "governance_decision_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "governance_chain_id",
            sa.String(length=255),
            nullable=True,
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.PrimaryKeyConstraint(
            "evaluation_id", name=op.f("pk_arbitration_evaluations")
        ),
    )
    op.create_index(
        op.f("ix_arbitration_evaluations_chain_id"),
        "arbitration_evaluations",
        ["chain_id"],
    )
    op.create_index(
        op.f("ix_arbitration_evaluations_case_id"),
        "arbitration_evaluations",
        ["case_id"],
    )
    op.create_index(
        op.f("ix_arbitration_evaluations_outcome"),
        "arbitration_evaluations",
        ["outcome"],
    )
    op.create_index(
        op.f("ix_arbitration_evaluations_correlation_id"),
        "arbitration_evaluations",
        ["correlation_id"],
    )
    op.create_index(
        op.f("ix_arbitration_evaluations_request_id"),
        "arbitration_evaluations",
        ["request_id"],
    )
    op.create_index(
        op.f("ix_arbitration_evaluations_tenant_id"),
        "arbitration_evaluations",
        ["tenant_id"],
    )
    op.create_index(
        op.f("ix_arbitration_evaluations_started_at"),
        "arbitration_evaluations",
        ["started_at"],
    )
    op.create_index(
        op.f("ix_arbitration_evaluations_governance_decision_id"),
        "arbitration_evaluations",
        ["governance_decision_id"],
    )
    op.create_index(
        "ix_arbitration_evaluations_runtime_seq",
        "arbitration_evaluations",
        ["runtime_instance_id", "sequence"],
    )


def downgrade() -> None:
    op.drop_table("arbitration_evaluations")
