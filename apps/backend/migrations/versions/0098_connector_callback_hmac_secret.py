"""Add callback_hmac_secret column to connector_configs.

Revision ID: 0098_connector_callback_hmac_secret
Revises: 0097_mvp7_customer_identity_id
Create Date: 2026-07-05

Adds a nullable Text column ``callback_hmac_secret`` to ``connector_configs``.
When populated with a non-empty string, the work-order fulfillment callback
endpoint requires an ``X-Operious-Signature: sha256=<hex>`` header on every
inbound request; if absent or mismatched the request is rejected 422.

When NULL (the default), the existing bearer-token path continues unchanged —
the migration is fully backwards-compatible.

Design choices:
  - Nullable: existing connector config rows receive NULL; no backfill needed.
  - Text type: secrets can be arbitrarily long; no width constraint imposed
    beyond the database-level CHECK that forbids empty strings.
  - CHECK constraint: ``callback_hmac_secret IS NULL OR
    length(callback_hmac_secret) > 0`` prevents accidentally storing an
    empty string that would silently disable signature enforcement.
  - No RLS change required: the existing FORCE ROW LEVEL SECURITY policy
    applied in migration 0087 already covers all columns on this table.

Zero-downtime: ``ADD COLUMN … DEFAULT NULL`` on Postgres 12+ is metadata-only
and does not rewrite the heap.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0098_connector_callback_hmac_secret"
down_revision: Union[str, None] = "0097_mvp7_customer_identity_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "connector_configs"
_COLUMN = "callback_hmac_secret"
_CONSTRAINT = "callback_hmac_secret_nonempty_if_set"


def upgrade() -> None:
    op.add_column(
        _TABLE,
        sa.Column(
            _COLUMN,
            sa.Text,
            nullable=True,
            comment=(
                "Optional HMAC-SHA256 shared secret for callback signature "
                "verification. If set, X-Operious-Signature must be present "
                "on inbound callbacks."
            ),
        ),
    )
    op.create_check_constraint(
        _CONSTRAINT,
        _TABLE,
        f"{_COLUMN} IS NULL OR length({_COLUMN}) > 0",
    )


def downgrade() -> None:
    op.drop_constraint(_CONSTRAINT, _TABLE, type_="check")
    op.drop_column(_TABLE, _COLUMN)
