"""dual-control data-protection erasure requests

Revision ID: 0068_erasure_dual_control
Revises: 0067_data_protection_controls
Create Date: 2026-06-02
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0068_erasure_dual_control"
down_revision: Union[str, None] = "0067_data_protection_controls"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE_NAME = "data_protection_erasure_requests"
_OLD_STATUS_CHECK = "ck_data_protection_erasure_requests_erasure_status_valid"
_NEW_STATUS_CHECK = "ck_data_protection_erasure_requests_erasure_status_valid"
_APPROVER_DISTINCT_CHECK = (
    "ck_data_protection_erasure_requests_erasure_approver_distinct"
)
_REASON_NONEMPTY_CHECK = "ck_data_protection_erasure_requests_erasure_reason_nonempty"


def upgrade() -> None:
    op.drop_constraint(
        op.f(_OLD_STATUS_CHECK),
        _TABLE_NAME,
        schema="public",
        type_="check",
    )
    op.alter_column(
        _TABLE_NAME,
        "requested_by",
        new_column_name="proposed_by",
        schema="public",
    )
    op.alter_column(
        _TABLE_NAME,
        "requested_at",
        new_column_name="proposed_at",
        schema="public",
    )
    op.alter_column(
        _TABLE_NAME,
        "completed_at",
        new_column_name="executed_at",
        schema="public",
    )
    op.add_column(
        _TABLE_NAME,
        sa.Column(
            "reason",
            sa.Text(),
            server_default=sa.text("'legacy erasure request'"),
            nullable=False,
        ),
        schema="public",
    )
    op.add_column(
        _TABLE_NAME,
        sa.Column("approved_by", sa.String(length=255), nullable=True),
        schema="public",
    )
    op.add_column(
        _TABLE_NAME,
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        schema="public",
    )
    op.alter_column(
        _TABLE_NAME,
        "reason",
        server_default=None,
        schema="public",
    )
    op.execute(
        f"""
        UPDATE public.{_TABLE_NAME}
           SET status = CASE status
               WHEN 'completed' THEN 'executed'
               WHEN 'blocked' THEN 'rejected'
               ELSE status
           END
        """
    )
    op.create_check_constraint(
        op.f(_NEW_STATUS_CHECK),
        _TABLE_NAME,
        "status IN ('proposed', 'approved', 'rejected', 'executed')",
        schema="public",
    )
    op.create_check_constraint(
        op.f(_APPROVER_DISTINCT_CHECK),
        _TABLE_NAME,
        "approved_by IS NULL OR approved_by != proposed_by",
        schema="public",
    )
    op.create_check_constraint(
        op.f(_REASON_NONEMPTY_CHECK),
        _TABLE_NAME,
        "length(reason) > 0",
        schema="public",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f(_REASON_NONEMPTY_CHECK),
        _TABLE_NAME,
        schema="public",
        type_="check",
    )
    op.drop_constraint(
        op.f(_APPROVER_DISTINCT_CHECK),
        _TABLE_NAME,
        schema="public",
        type_="check",
    )
    op.drop_constraint(
        op.f(_NEW_STATUS_CHECK),
        _TABLE_NAME,
        schema="public",
        type_="check",
    )
    op.execute(
        f"""
        UPDATE public.{_TABLE_NAME}
           SET status = CASE status
               WHEN 'executed' THEN 'completed'
               ELSE 'blocked'
           END
        """
    )
    op.drop_column(_TABLE_NAME, "approved_at", schema="public")
    op.drop_column(_TABLE_NAME, "approved_by", schema="public")
    op.drop_column(_TABLE_NAME, "reason", schema="public")
    op.alter_column(
        _TABLE_NAME,
        "executed_at",
        new_column_name="completed_at",
        schema="public",
    )
    op.alter_column(
        _TABLE_NAME,
        "proposed_at",
        new_column_name="requested_at",
        schema="public",
    )
    op.alter_column(
        _TABLE_NAME,
        "proposed_by",
        new_column_name="requested_by",
        schema="public",
    )
    op.create_check_constraint(
        op.f(_OLD_STATUS_CHECK),
        _TABLE_NAME,
        "status IN ('completed', 'blocked')",
        schema="public",
    )
