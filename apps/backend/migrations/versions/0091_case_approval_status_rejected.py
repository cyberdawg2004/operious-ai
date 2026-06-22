"""case_approval_records status: add 'rejected'

Revision ID: 0091_case_approval_status_rejected
Revises: 0090_tenant_knowledge_template_fields
Create Date: 2026-06-22

A manager reviewing a grounded warranty/refund recommendation needs a
terminal "no" distinct from escalate (which hands the case to a
DIFFERENT queue for further human handling, not a final denial).
Rejecting records the disposition with no connector firing — same
status-column shape as every other lifecycle value, just one more
entry in the existing CHECK constraint.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0091_case_approval_status_rejected"
down_revision: Union[str, None] = "0090_tenant_knowledge_template_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "case_approval_records"
_CONSTRAINT = "case_approval_status_valid"


def upgrade() -> None:
    op.drop_constraint(_CONSTRAINT, _TABLE, schema="public", type_="check")
    op.create_check_constraint(
        _CONSTRAINT,
        _TABLE,
        "status IN ("
        "'pending_sme_review', "
        "'awaiting_approval', "
        "'guidance_in_progress', "
        "'approved', "
        "'rejected', "
        "'escalated', "
        "'failed')",
        schema="public",
    )


def downgrade() -> None:
    op.drop_constraint(_CONSTRAINT, _TABLE, schema="public", type_="check")
    op.create_check_constraint(
        _CONSTRAINT,
        _TABLE,
        "status IN ("
        "'pending_sme_review', "
        "'awaiting_approval', "
        "'guidance_in_progress', "
        "'approved', "
        "'escalated', "
        "'failed')",
        schema="public",
    )
