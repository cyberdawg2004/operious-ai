"""create session tables (PR-B3)

Three tables backing the Postgres :class:`SessionPersistenceProtocol`
implementation:

* ``operational_sessions``  — apex session records (revision-monotonic).
* ``session_events``        — append-only timeline (contiguous sequence).
* ``session_correlations``  — cross-substrate correlation observations.

Doctrine notes (see ``app/session/db/models.py``):

* ``tenant_id`` is nullable on ``operational_sessions``. Sessions
  almost always carry a tenant in production, but the in-memory
  contract accepts None and the schema mirrors that. Phase 5 may
  add ``NOT NULL`` + tenant partitioning once the runtime contract
  forbids tenantless sessions.
* ``session_events`` has ``UNIQUE (session_id, sequence)`` as the
  database backstop against concurrent producers landing duplicate
  sequences; the substrate layer additionally enforces contiguity
  from 0.
* RESTRICT FKs from events / correlations to sessions so an apex
  session can never be silently orphaned.
* JSONB columns for tuple/mapping fields; discrete columns for
  every scalar the substrate filters on.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_session"
down_revision: Union[str, None] = "0005_governance"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "operational_sessions",
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column(
            "external_handle", sa.String(length=255), nullable=False
        ),
        sa.Column("tenant_id", sa.String(length=255), nullable=True),
        sa.Column(
            "principal_id", sa.String(length=255), nullable=True
        ),
        sa.Column(
            "opened_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "lifecycle_phase", sa.String(length=32), nullable=False
        ),
        sa.Column(
            "lifecycle_recorded_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "lifecycle_reason", sa.Text(), nullable=True
        ),
        sa.Column(
            "lineage_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "root_session_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "parent_session_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "ancestor_session_ids",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("lineage_depth", sa.Integer(), nullable=False),
        sa.Column("sequence_head", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column(
            "context_environment",
            sa.String(length=255),
            nullable=True,
        ),
        sa.Column(
            "context_labels",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "context_attributes",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "context_notes", sa.Text(), nullable=True
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.PrimaryKeyConstraint(
            "session_id", name=op.f("pk_operational_sessions")
        ),
    )
    op.create_index(
        op.f("ix_operational_sessions_external_handle"),
        "operational_sessions",
        ["external_handle"],
    )
    op.create_index(
        op.f("ix_operational_sessions_tenant_id"),
        "operational_sessions",
        ["tenant_id"],
    )
    op.create_index(
        op.f("ix_operational_sessions_principal_id"),
        "operational_sessions",
        ["principal_id"],
    )
    op.create_index(
        op.f("ix_operational_sessions_opened_at"),
        "operational_sessions",
        ["opened_at"],
    )
    op.create_index(
        op.f("ix_operational_sessions_lifecycle_phase"),
        "operational_sessions",
        ["lifecycle_phase"],
    )
    op.create_index(
        op.f("ix_operational_sessions_lineage_id"),
        "operational_sessions",
        ["lineage_id"],
    )
    op.create_index(
        op.f("ix_operational_sessions_root_session_id"),
        "operational_sessions",
        ["root_session_id"],
    )

    op.create_table(
        "session_events",
        sa.Column(
            "event_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column(
            "continuity_mode", sa.String(length=32), nullable=False
        ),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "payload",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "correlation_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("annotation", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["operational_sessions.session_id"],
            name=op.f(
                "fk_session_events_session_id_operational_sessions"
            ),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "event_id", name=op.f("pk_session_events")
        ),
        sa.UniqueConstraint(
            "session_id",
            "sequence",
            name="uq_session_events_session_id_sequence",
        ),
    )
    op.create_index(
        op.f("ix_session_events_session_id"),
        "session_events",
        ["session_id"],
    )
    op.create_index(
        op.f("ix_session_events_kind"),
        "session_events",
        ["kind"],
    )
    op.create_index(
        op.f("ix_session_events_occurred_at"),
        "session_events",
        ["occurred_at"],
    )
    op.create_index(
        op.f("ix_session_events_correlation_id"),
        "session_events",
        ["correlation_id"],
    )
    op.create_index(
        op.f("ix_session_events_governance_decision_id"),
        "session_events",
        ["governance_decision_id"],
    )

    op.create_table(
        "session_correlations",
        sa.Column(
            "correlation_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column(
            "external_id", sa.String(length=255), nullable=False
        ),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "external_correlation_id",
            sa.String(length=255),
            nullable=True,
        ),
        sa.Column("annotation", sa.Text(), nullable=True),
        sa.Column(
            "attributes",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["operational_sessions.session_id"],
            name=op.f(
                "fk_session_correlations_session_id_operational_sessions"
            ),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "correlation_id", name=op.f("pk_session_correlations")
        ),
    )
    op.create_index(
        op.f("ix_session_correlations_session_id"),
        "session_correlations",
        ["session_id"],
    )
    op.create_index(
        op.f("ix_session_correlations_kind"),
        "session_correlations",
        ["kind"],
    )
    op.create_index(
        op.f("ix_session_correlations_external_id"),
        "session_correlations",
        ["external_id"],
    )
    op.create_index(
        op.f("ix_session_correlations_recorded_at"),
        "session_correlations",
        ["recorded_at"],
    )


def downgrade() -> None:
    op.drop_table("session_correlations")
    op.drop_table("session_events")
    op.drop_table("operational_sessions")
