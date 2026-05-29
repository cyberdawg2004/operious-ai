"""add resolution proposal cross-substrate foreign keys

Revision ID: 0057_resolution_fk_constraints
Revises: 0056_semantic_quarantine
Create Date: 2026-05-30
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0057_resolution_fk_constraints"
down_revision: Union[str, None] = "0056_semantic_quarantine"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    connection = op.get_bind()
    _ensure_no_orphans(
        connection,
        field_name="session_id",
        sql="""
        SELECT count(*)
        FROM public.resolution_proposals rp
        LEFT JOIN public.operational_sessions s
          ON rp.session_id = s.session_id
        WHERE rp.session_id IS NOT NULL
          AND s.session_id IS NULL
        """,
    )
    _ensure_no_orphans(
        connection,
        field_name="execution_id",
        sql="""
        SELECT count(*)
        FROM public.resolution_proposals rp
        LEFT JOIN public.execution_records e
          ON rp.execution_id = e.execution_id
        WHERE rp.execution_id IS NOT NULL
          AND e.execution_id IS NULL
        """,
    )
    _ensure_no_orphans(
        connection,
        field_name="governance_decision_id",
        sql="""
        SELECT count(*)
        FROM public.resolution_proposals rp
        LEFT JOIN public.governance_decisions gd
          ON rp.governance_decision_id = gd.decision_id
        WHERE rp.governance_decision_id IS NOT NULL
          AND gd.decision_id IS NULL
        """,
    )

    op.alter_column(
        "resolution_proposals",
        "session_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=True,
        schema="public",
    )
    op.alter_column(
        "resolution_proposals",
        "execution_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=True,
        schema="public",
    )
    op.create_foreign_key(
        "fk_resolution_proposals_session_id",
        "resolution_proposals",
        "operational_sessions",
        ["session_id"],
        ["session_id"],
        source_schema="public",
        referent_schema="public",
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_resolution_proposals_execution_id",
        "resolution_proposals",
        "execution_records",
        ["execution_id"],
        ["execution_id"],
        source_schema="public",
        referent_schema="public",
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_resolution_proposals_governance_decision_id",
        "resolution_proposals",
        "governance_decisions",
        ["governance_decision_id"],
        ["decision_id"],
        source_schema="public",
        referent_schema="public",
        ondelete="SET NULL",
    )


def downgrade() -> None:
    connection = op.get_bind()
    _ensure_no_nulls(
        connection,
        field_name="session_id",
        sql="""
        SELECT count(*)
        FROM public.resolution_proposals
        WHERE session_id IS NULL
        """,
    )
    _ensure_no_nulls(
        connection,
        field_name="execution_id",
        sql="""
        SELECT count(*)
        FROM public.resolution_proposals
        WHERE execution_id IS NULL
        """,
    )
    op.drop_constraint(
        "fk_resolution_proposals_governance_decision_id",
        "resolution_proposals",
        schema="public",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_resolution_proposals_execution_id",
        "resolution_proposals",
        schema="public",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_resolution_proposals_session_id",
        "resolution_proposals",
        schema="public",
        type_="foreignkey",
    )
    op.alter_column(
        "resolution_proposals",
        "execution_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
        schema="public",
    )
    op.alter_column(
        "resolution_proposals",
        "session_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
        schema="public",
    )


def _ensure_no_orphans(
    connection: sa.engine.Connection,
    *,
    field_name: str,
    sql: str,
) -> None:
    orphaned = _count(connection, sql)
    if orphaned > 0:
        raise RuntimeError(
            f"Cannot add FK: {orphaned} orphaned {field_name} "
            "references in resolution_proposals"
        )


def _ensure_no_nulls(
    connection: sa.engine.Connection,
    *,
    field_name: str,
    sql: str,
) -> None:
    null_count = _count(connection, sql)
    if null_count > 0:
        raise RuntimeError(
            f"Cannot downgrade resolution FK migration: {null_count} "
            f"resolution_proposals.{field_name} values are NULL"
        )


def _count(connection: sa.engine.Connection, sql: str) -> int:
    value = connection.execute(sa.text(sql)).scalar()
    return int(value or 0)
