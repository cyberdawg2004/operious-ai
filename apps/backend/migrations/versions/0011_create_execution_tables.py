"""create execution authority tables (Phase 1-A)

Two tables close the first execution-sovereignty wedge:

* execution_records — one durable authority row per worker execution.
* execution_outbox  — one durable transport intent per execution.

Doctrine:

* ``dispatch_id`` is NOT ``execution_id``. The unique
  ``(tenant_id, dispatch_id, kind)`` constraint prevents duplicate
  execution authority for the same dispatch.
* Celery remains transport only; workers claim ``execution_id`` before
  reading dispatch/session lineage or mutating timeline projections.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011_execution"
down_revision: Union[str, None] = "0010_boundary"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "execution_records",
        sa.Column(
            "execution_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("dispatch_id", sa.String(length=255), nullable=False),
        sa.Column("session_id", sa.String(length=255), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("state", sa.String(length=64), nullable=False),
        sa.Column(
            "attempt_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "completed_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("worker_id", sa.String(length=255), nullable=True),
        sa.Column(
            "result",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "execution_id", name=op.f("pk_execution_records")
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "dispatch_id",
            "kind",
            name="uq_execution_records_tenant_dispatch_kind",
        ),
    )
    for col in (
        "kind",
        "dispatch_id",
        "session_id",
        "tenant_id",
        "state",
        "requested_at",
        "worker_id",
    ):
        op.create_index(
            op.f(f"ix_execution_records_{col}"),
            "execution_records",
            [col],
        )
    op.create_table(
        "execution_attempts",
        sa.Column(
            "attempt_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "execution_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=64), nullable=False),
        sa.Column("worker_id", sa.String(length=255), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "completed_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "previous_attempt_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "retry_requested",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "result",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["execution_id"],
            ["execution_records.execution_id"],
            name=op.f(
                "fk_execution_attempts_execution_id_execution_records"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["previous_attempt_id"],
            ["execution_attempts.attempt_id"],
            name=op.f("fk_execution_attempts_previous_attempt_id"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint(
            "attempt_id", name=op.f("pk_execution_attempts")
        ),
        sa.UniqueConstraint(
            "execution_id",
            "attempt_number",
            name="uq_execution_attempts_execution_attempt_number",
        ),
    )
    for col in (
        "execution_id",
        "state",
        "worker_id",
        "started_at",
        "previous_attempt_id",
    ):
        op.create_index(
            op.f(f"ix_execution_attempts_{col}"),
            "execution_attempts",
            [col],
        )
    op.create_table(
        "execution_outbox",
        sa.Column(
            "outbox_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "execution_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("state", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "published_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("publisher_id", sa.String(length=255), nullable=True),
        sa.Column(
            "publish_attempt_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["execution_id"],
            ["execution_records.execution_id"],
            name=op.f(
                "fk_execution_outbox_execution_id_execution_records"
            ),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "outbox_id", name=op.f("pk_execution_outbox")
        ),
    )
    for col in ("execution_id", "state", "created_at", "publisher_id"):
        op.create_index(
            op.f(f"ix_execution_outbox_{col}"),
            "execution_outbox",
            [col],
        )


def downgrade() -> None:
    op.drop_table("execution_outbox")
    op.drop_table("execution_attempts")
    op.drop_table("execution_records")
