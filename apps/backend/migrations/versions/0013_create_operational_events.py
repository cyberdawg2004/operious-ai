"""create canonical operational event fabric tables (Phase 2-A)

Revision ID: 0013_operational_events
Revises: 0012_session_event_idempotency
Create Date: 2026-05-22 00:00:00.000000

Phase 2-A establishes durable append authority for canonical
OperationalEvent records. It does not migrate session timeline events
or wire producers yet; adoption belongs to later Phase 2 slices.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013_operational_events"
down_revision: Union[str, None] = "0012_session_event_idempotency"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "operational_events",
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("operational_act", sa.String(length=96), nullable=False),
        sa.Column("substrate", sa.String(length=96), nullable=False),
        sa.Column(
            "root_event_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column(
            "parent_event_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column("causality_depth", sa.Integer(), nullable=False),
        sa.Column(
            "runtime_instance_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=True),
        sa.Column("principal_id", sa.String(length=255), nullable=True),
        sa.Column("organization_id", sa.String(length=255), nullable=True),
        sa.Column("environment_id", sa.String(length=255), nullable=True),
        sa.Column(
            "tenant_authority_source", sa.String(length=255), nullable=True
        ),
        sa.Column("governance_decision", sa.String(length=96), nullable=True),
        sa.Column(
            "governance_decision_id", sa.String(length=255), nullable=True
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("event_id", name=op.f("pk_operational_events")),
        sa.UniqueConstraint(
            "runtime_instance_id",
            "sequence",
            name="uq_operational_events_runtime_sequence",
        ),
    )
    for col in (
        "operational_act",
        "substrate",
        "root_event_id",
        "parent_event_id",
        "runtime_instance_id",
        "occurred_at",
        "tenant_id",
        "governance_decision_id",
    ):
        op.create_index(
            op.f(f"ix_operational_events_{col}"),
            "operational_events",
            [col],
        )


def downgrade() -> None:
    op.drop_table("operational_events")
