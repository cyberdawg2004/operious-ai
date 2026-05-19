"""create coordination tables (PR-B4)

Single table: ``coordination_envelopes``. One row per dispatched
envelope; every supplementary fact (sender, sequence, lineage,
governance link, payload, metadata bags) is a column on the same row.

Doctrine notes (see ``app/coordination/db/models.py``):

* Nullable ``tenant_id`` (broadcast / system envelopes may be
  tenantless); no partitioning yet.
* Composite index ``(runtime_instance_id, sequence)`` for the
  canonical global ordering the Protocol guarantees.
* JSONB blobs for payload + every metadata bag.
* No FKs to other substrates — ``governance_decision_id`` is a
  pure join handle; replay tools assemble decisions by id without
  a relational chain.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_coordination"
down_revision: Union[str, None] = "0006_session"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "coordination_envelopes",
        sa.Column(
            "coordination_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "message_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("sender_id", sa.String(length=255), nullable=False),
        sa.Column(
            "recipient_id", sa.String(length=255), nullable=False
        ),
        sa.Column(
            "recipient_kind", sa.String(length=32), nullable=False
        ),
        sa.Column("direction", sa.String(length=32), nullable=False),
        sa.Column(
            "message_type", sa.String(length=32), nullable=False
        ),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column(
            "runtime_instance_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "correlation_id", sa.String(length=255), nullable=True
        ),
        sa.Column(
            "parent_coordination_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "parent_message_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "in_reply_to",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("request_id", sa.String(length=255), nullable=True),
        sa.Column("tenant_id", sa.String(length=255), nullable=True),
        sa.Column(
            "tenant_authority_source",
            sa.String(length=32),
            nullable=True,
        ),
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
            "payload_content_type",
            sa.String(length=255),
            nullable=False,
        ),
        sa.Column(
            "payload_schema_version",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'1'"),
        ),
        sa.Column(
            "payload_body",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "dispatched_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "recipient_metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "payload_metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "message_metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "envelope_metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.PrimaryKeyConstraint(
            "coordination_id", name=op.f("pk_coordination_envelopes")
        ),
    )
    op.create_index(
        op.f("ix_coordination_envelopes_message_id"),
        "coordination_envelopes",
        ["message_id"],
    )
    op.create_index(
        op.f("ix_coordination_envelopes_sender_id"),
        "coordination_envelopes",
        ["sender_id"],
    )
    op.create_index(
        op.f("ix_coordination_envelopes_recipient_id"),
        "coordination_envelopes",
        ["recipient_id"],
    )
    op.create_index(
        op.f("ix_coordination_envelopes_direction"),
        "coordination_envelopes",
        ["direction"],
    )
    op.create_index(
        op.f("ix_coordination_envelopes_message_type"),
        "coordination_envelopes",
        ["message_type"],
    )
    op.create_index(
        op.f("ix_coordination_envelopes_status"),
        "coordination_envelopes",
        ["status"],
    )
    op.create_index(
        op.f("ix_coordination_envelopes_correlation_id"),
        "coordination_envelopes",
        ["correlation_id"],
    )
    op.create_index(
        op.f("ix_coordination_envelopes_parent_coordination_id"),
        "coordination_envelopes",
        ["parent_coordination_id"],
    )
    op.create_index(
        op.f("ix_coordination_envelopes_request_id"),
        "coordination_envelopes",
        ["request_id"],
    )
    op.create_index(
        op.f("ix_coordination_envelopes_tenant_id"),
        "coordination_envelopes",
        ["tenant_id"],
    )
    op.create_index(
        op.f("ix_coordination_envelopes_governance_decision_id"),
        "coordination_envelopes",
        ["governance_decision_id"],
    )
    op.create_index(
        op.f("ix_coordination_envelopes_created_at"),
        "coordination_envelopes",
        ["created_at"],
    )
    # Composite for canonical global ordering.
    op.create_index(
        "ix_coordination_envelopes_runtime_seq",
        "coordination_envelopes",
        ["runtime_instance_id", "sequence"],
    )


def downgrade() -> None:
    op.drop_table("coordination_envelopes")
