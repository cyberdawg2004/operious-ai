"""cascade ingress dispatch outbox when boundary ingress is deleted

Revision ID: 0082_ingress_dispatch_outbox_cascade_fk
Revises: 0081_ingress_dispatch_outbox
Create Date: 2026-06-09
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0082_ingress_dispatch_outbox_cascade_fk"
down_revision: str | None = "0081_ingress_dispatch_outbox"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "ingress_dispatch_outbox"
_CONSTRAINT = "fk_ingress_dispatch_outbox_ingress_id_boundary_ingress"


def upgrade() -> None:
    op.drop_constraint(_CONSTRAINT, _TABLE, type_="foreignkey", schema="public")
    op.create_foreign_key(
        _CONSTRAINT,
        _TABLE,
        "boundary_ingress",
        ["ingress_id"],
        ["ingress_id"],
        source_schema="public",
        referent_schema="public",
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(_CONSTRAINT, _TABLE, type_="foreignkey", schema="public")
    op.create_foreign_key(
        _CONSTRAINT,
        _TABLE,
        "boundary_ingress",
        ["ingress_id"],
        ["ingress_id"],
        source_schema="public",
        referent_schema="public",
        ondelete="RESTRICT",
    )
