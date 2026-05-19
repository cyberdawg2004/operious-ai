"""create boundary tables (PR-B7)

Two tables backing the Postgres BoundaryPersistenceProtocol
implementation:

* boundary_ingress  — one row per ``ingest()`` outcome.
* boundary_egress   — one row per ``emit()`` outcome.

Doctrine: nullable tenant_id; no partitioning yet. Composite
(runtime_instance_id, sequence) on each table for the canonical
ordering. JSONB blobs for canonical_payload, payload_body,
payload_headers, metadata.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010_boundary"
down_revision: Union[str, None] = "0009_supervisor"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "boundary_ingress",
        sa.Column(
            "ingress_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("direction", sa.String(length=64), nullable=False),
        sa.Column(
            "runtime_instance_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column(
            "source_type", sa.String(length=64), nullable=False
        ),
        sa.Column("source_id", sa.String(length=255), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=True),
        sa.Column(
            "adapter_name", sa.String(length=255), nullable=False
        ),
        sa.Column(
            "normalization_status",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "message_type", sa.String(length=64), nullable=False
        ),
        sa.Column(
            "replay_disposition",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "replay_key",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "event_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "original_event_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "external_message_id",
            sa.String(length=255),
            nullable=True,
        ),
        sa.Column(
            "external_conversation_id",
            sa.String(length=255),
            nullable=True,
        ),
        sa.Column(
            "external_emitted_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            nullable=False,
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
        sa.Column(
            "correlation_id", sa.String(length=255), nullable=True
        ),
        sa.Column("request_id", sa.String(length=255), nullable=True),
        sa.Column(
            "canonical_payload",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.PrimaryKeyConstraint(
            "ingress_id", name=op.f("pk_boundary_ingress")
        ),
    )
    for col in (
        "direction",
        "source_type",
        "source_id",
        "tenant_id",
        "adapter_name",
        "normalization_status",
        "message_type",
        "replay_disposition",
        "replay_key",
        "event_id",
        "external_conversation_id",
        "received_at",
        "correlation_id",
        "request_id",
    ):
        op.create_index(
            op.f(f"ix_boundary_ingress_{col}"),
            "boundary_ingress",
            [col],
        )
    op.create_index(
        "ix_boundary_ingress_runtime_seq",
        "boundary_ingress",
        ["runtime_instance_id", "sequence"],
    )

    op.create_table(
        "boundary_egress",
        sa.Column(
            "egress_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("direction", sa.String(length=64), nullable=False),
        sa.Column(
            "runtime_instance_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column(
            "source_type", sa.String(length=64), nullable=False
        ),
        sa.Column("source_id", sa.String(length=255), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=True),
        sa.Column(
            "adapter_name", sa.String(length=255), nullable=False
        ),
        sa.Column(
            "payload_body",
            postgresql.JSONB(),
            nullable=False,
        ),
        sa.Column(
            "payload_content_type",
            sa.String(length=255),
            nullable=True,
        ),
        sa.Column(
            "payload_target_uri",
            sa.String(length=1020),
            nullable=True,
        ),
        sa.Column(
            "payload_method", sa.String(length=64), nullable=True
        ),
        sa.Column(
            "payload_headers",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "translated_at",
            sa.DateTime(timezone=True),
            nullable=False,
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
        sa.Column(
            "correlation_id", sa.String(length=255), nullable=True
        ),
        sa.Column("request_id", sa.String(length=255), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.PrimaryKeyConstraint(
            "egress_id", name=op.f("pk_boundary_egress")
        ),
    )
    for col in (
        "direction",
        "source_type",
        "source_id",
        "tenant_id",
        "adapter_name",
        "started_at",
        "correlation_id",
        "request_id",
    ):
        op.create_index(
            op.f(f"ix_boundary_egress_{col}"),
            "boundary_egress",
            [col],
        )
    op.create_index(
        "ix_boundary_egress_runtime_seq",
        "boundary_egress",
        ["runtime_instance_id", "sequence"],
    )


def downgrade() -> None:
    op.drop_table("boundary_egress")
    op.drop_table("boundary_ingress")
