"""add multilingual source language fields

Revision ID: 0052_boundary_ingress_language
Revises: 0051_training_recommendations
Create Date: 2026-05-29
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0052_boundary_ingress_language"
down_revision: Union[str, None] = "0051_training_recommendations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "boundary_ingress",
        sa.Column(
            "source_language",
            sa.String(length=16),
            server_default=sa.text("'en'"),
            nullable=False,
        ),
        schema="public",
    )
    op.create_index(
        "ix_boundary_ingress_tenant_language",
        "boundary_ingress",
        ["tenant_id", "source_language"],
        unique=False,
        schema="public",
        postgresql_where=sa.text("source_language != 'en'"),
    )
    op.add_column(
        "resolution_proposals",
        sa.Column(
            "source_language",
            sa.String(length=64),
            server_default=sa.text("'en'"),
            nullable=False,
        ),
        schema="public",
    )
    op.add_column(
        "resolution_outbound_drafts",
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        schema="public",
    )


def downgrade() -> None:
    op.drop_column(
        "resolution_outbound_drafts",
        "metadata",
        schema="public",
    )
    op.drop_column(
        "resolution_proposals",
        "source_language",
        schema="public",
    )
    op.drop_index(
        "ix_boundary_ingress_tenant_language",
        table_name="boundary_ingress",
        schema="public",
    )
    op.drop_column(
        "boundary_ingress",
        "source_language",
        schema="public",
    )
