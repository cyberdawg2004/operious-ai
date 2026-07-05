"""MVP-7: add customer_identity_id to operational_sessions.

Revision ID: 0097_mvp7_customer_identity_id
Revises: 0096_sme_resolution_proposal_metadata
Create Date: 2026-07-05

Adds a nullable UUID column ``customer_identity_id`` to
``operational_sessions``. When ``IdentityResolutionRuntime`` matches an
inbound session to a prior cross-channel session, both rows are stamped
with the same ``customer_identity_id``. This enables the timeline view
and supervisor inbox to surface all tickets from the same customer across
email, WhatsApp, voice, and any other channel.

Design choices:
  - Nullable: pre-migration rows and tickets with no cross-channel match
    remain NULL — never a blocker.
  - UUID type: deterministically derived from tenant + external identity
    signals (same derivation as all other substrate IDs).
  - No foreign key: customer_identity_id is a soft correlation key, not a
    reference to a separate entity table. This keeps the migration additive
    and avoids a cascade-on-delete footgun.
  - Index: partial index on non-NULL rows only — the common query is
    "find all sessions for this customer_identity_id" and most rows are NULL.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0097_mvp7_customer_identity_id"
down_revision: Union[str, None] = "0096_sme_resolution_proposal_metadata"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "operational_sessions",
        sa.Column(
            "customer_identity_id",
            pg.UUID(as_uuid=True),
            nullable=True,
            comment="Cross-channel customer identity correlation key (MVP-7).",
        ),
    )
    op.create_index(
        "ix_operational_sessions_customer_identity_id",
        "operational_sessions",
        ["customer_identity_id"],
        unique=False,
        postgresql_where=sa.text("customer_identity_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_operational_sessions_customer_identity_id",
        table_name="operational_sessions",
    )
    op.drop_column("operational_sessions", "customer_identity_id")
