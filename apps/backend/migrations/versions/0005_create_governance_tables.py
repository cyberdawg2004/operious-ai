"""create governance tables (PR-B2)

Three tables backing the Postgres ``BaseGovernanceRepository``
implementation:

* ``governance_decisions``         — apex verdicts.
* ``governance_traces``            — 1:1 per-evaluation forensic traces.
* ``governance_enforcement_actions`` — N:1 per-handler execution records.

Doctrine choices (see ``app/governance/db/models.py``):

* ``tenant_id`` is nullable on decisions/traces — governance MAY
  persist tenantless (system-level) decisions. Row-level isolation
  via ``WHERE tenant_id = $expected`` correctly excludes ``NULL``
  via SQL three-valued logic.
* No tenant partitioning — partitioning requires NOT NULL partition
  keys, and governance is read-rare relative to session ingest.
* JSONB blobs for nested structs (violations / restrictions /
  evaluated_rules / policy_traces / metadata) so the substrate's
  ``to_dict`` / ``from_dict`` round-trip is lossless without side
  tables.
* RESTRICT FKs on traces / enforcement_actions → decisions so a
  decision can never be silently orphaned.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_governance"
down_revision: Union[str, None] = "0004_drop_legacy"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "governance_decisions",
        sa.Column(
            "decision_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column(
            "policy_chain_id", sa.String(length=255), nullable=False
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "decided_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "correlation_id", sa.String(length=255), nullable=True
        ),
        sa.Column("request_id", sa.String(length=255), nullable=True),
        sa.Column("tenant_id", sa.String(length=255), nullable=True),
        sa.Column(
            "subject_kind",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'generic'"),
        ),
        sa.Column(
            "governance_version",
            sa.String(length=128),
            nullable=False,
            server_default=sa.text("'unversioned'"),
        ),
        sa.Column(
            "violations",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "restrictions",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "evaluated_rules",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.PrimaryKeyConstraint(
            "decision_id", name=op.f("pk_governance_decisions")
        ),
    )
    op.create_index(
        op.f("ix_governance_decisions_policy_chain_id"),
        "governance_decisions",
        ["policy_chain_id"],
    )
    op.create_index(
        op.f("ix_governance_decisions_decided_at"),
        "governance_decisions",
        ["decided_at"],
    )
    op.create_index(
        op.f("ix_governance_decisions_correlation_id"),
        "governance_decisions",
        ["correlation_id"],
    )
    op.create_index(
        op.f("ix_governance_decisions_request_id"),
        "governance_decisions",
        ["request_id"],
    )
    op.create_index(
        op.f("ix_governance_decisions_tenant_id"),
        "governance_decisions",
        ["tenant_id"],
    )
    # Composite index for the dominant audit pattern:
    # "every decision for this tenant in this time range".
    op.create_index(
        "ix_governance_decisions_tenant_id_decided_at",
        "governance_decisions",
        ["tenant_id", "decided_at"],
    )

    op.create_table(
        "governance_traces",
        sa.Column(
            "decision_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "request_id", sa.String(length=255), nullable=True
        ),
        sa.Column(
            "correlation_id", sa.String(length=255), nullable=True
        ),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column("action", sa.String(length=255), nullable=False),
        sa.Column("resource", sa.String(length=255), nullable=False),
        sa.Column("actor", sa.String(length=255), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=True),
        sa.Column(
            "subject_kind",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'generic'"),
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
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "final_decision", sa.String(length=32), nullable=False
        ),
        sa.Column(
            "policy_chain_id", sa.String(length=255), nullable=False
        ),
        sa.Column("rule_count", sa.Integer(), nullable=False),
        sa.Column("violation_count", sa.Integer(), nullable=False),
        sa.Column("restriction_count", sa.Integer(), nullable=False),
        sa.Column(
            "enforcement_handler",
            sa.String(length=255),
            nullable=True,
        ),
        sa.Column(
            "enforcement_status",
            sa.String(length=32),
            nullable=True,
        ),
        sa.Column(
            "enforcement_latency_ms", sa.Float(), nullable=True
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "policy_traces",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.ForeignKeyConstraint(
            ["decision_id"],
            ["governance_decisions.decision_id"],
            name=op.f(
                "fk_governance_traces_decision_id_governance_decisions"
            ),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "decision_id", name=op.f("pk_governance_traces")
        ),
    )
    op.create_index(
        op.f("ix_governance_traces_request_id"),
        "governance_traces",
        ["request_id"],
    )
    op.create_index(
        op.f("ix_governance_traces_correlation_id"),
        "governance_traces",
        ["correlation_id"],
    )
    op.create_index(
        op.f("ix_governance_traces_tenant_id"),
        "governance_traces",
        ["tenant_id"],
    )
    op.create_index(
        op.f("ix_governance_traces_started_at"),
        "governance_traces",
        ["started_at"],
    )

    op.create_table(
        "governance_enforcement_actions",
        sa.Column(
            "action_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "decision_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "handler_name", sa.String(length=255), nullable=False
        ),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column(
            "applied_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "detail",
            sa.Text(),
            nullable=False,
            server_default=sa.text("''"),
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.ForeignKeyConstraint(
            ["decision_id"],
            ["governance_decisions.decision_id"],
            name=op.f(
                "fk_governance_enforcement_actions_decision_id_governance_decisions"
            ),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "action_id",
            name=op.f("pk_governance_enforcement_actions"),
        ),
    )
    op.create_index(
        op.f("ix_governance_enforcement_actions_decision_id"),
        "governance_enforcement_actions",
        ["decision_id"],
    )
    op.create_index(
        op.f("ix_governance_enforcement_actions_handler_name"),
        "governance_enforcement_actions",
        ["handler_name"],
    )
    op.create_index(
        op.f("ix_governance_enforcement_actions_applied_at"),
        "governance_enforcement_actions",
        ["applied_at"],
    )


def downgrade() -> None:
    op.drop_table("governance_enforcement_actions")
    op.drop_table("governance_traces")
    op.drop_table("governance_decisions")
