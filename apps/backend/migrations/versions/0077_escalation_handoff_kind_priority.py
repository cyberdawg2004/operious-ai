"""Add escalation handoff kind and priority.

Revision ID: 0077_escalation_handoff_kind_priority
Revises: 0076_cognition_semantic_rejection_forensics
Create Date: 2026-06-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0077_escalation_handoff_kind_priority"
down_revision: str | None = "0076_cognition_semantic_rejection_forensics"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "escalation_records",
        sa.Column(
            "handoff_kind",
            sa.String(length=32),
            nullable=False,
            server_default="denial",
        ),
    )
    op.add_column(
        "escalation_records",
        sa.Column(
            "priority",
            sa.String(length=32),
            nullable=False,
            server_default="normal",
        ),
    )
    op.create_check_constraint(
        "handoff_kind_valid",
        "escalation_records",
        "handoff_kind IN ('denial', 'escalation', 'crisis')",
    )
    op.create_check_constraint(
        "priority_valid",
        "escalation_records",
        "priority IN ('normal', 'high')",
    )
    op.create_index(
        "ix_escalation_records_handoff_kind",
        "escalation_records",
        ["handoff_kind"],
    )
    op.create_index(
        "ix_escalation_records_priority",
        "escalation_records",
        ["priority"],
    )
    op.create_index(
        "ix_escalation_records_tenant_status_priority",
        "escalation_records",
        ["tenant_id", "status", "priority"],
    )
    op.execute("ALTER TABLE public.escalation_records FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_index(
        "ix_escalation_records_tenant_status_priority",
        table_name="escalation_records",
    )
    op.drop_index("ix_escalation_records_priority", table_name="escalation_records")
    op.drop_index(
        "ix_escalation_records_handoff_kind",
        table_name="escalation_records",
    )
    op.drop_constraint(
        "priority_valid",
        "escalation_records",
        type_="check",
    )
    op.drop_constraint(
        "handoff_kind_valid",
        "escalation_records",
        type_="check",
    )
    op.drop_column("escalation_records", "priority")
    op.drop_column("escalation_records", "handoff_kind")
