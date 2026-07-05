"""MVP-6: add semantic_grounding column to qa_score_records.

Revision ID: 0095_mvp6_semantic_qa_grounding
Revises: 0094_mvp1_extraction_schema_agnosticism
Create Date: 2026-07-04

The SemanticQAAgent (MVP-6) extends the existing QA scoring pipeline with
a fifth dimension: semantic_grounding, which measures whether the cited KB
excerpts actually support the claims in the resolution reply. The four
existing deterministic dimensions (diagnostic_accuracy, policy_compliance,
timeline_integrity, resolution_quality) score rule compliance; this new
dimension scores citation semantic relevance.

Column: semantic_grounding DOUBLE PRECISION NOT NULL DEFAULT 0.0
  - 0.0: not yet scored (pre-MVP-6 rows, or proposals with no citations)
  - 0.0–1.0: normalised grounding quality produced by SemanticQAAgent
  - Existing rows backfill to 0.0 (not yet scored, not a failure)
  - New check constraint mirrors the four existing dimension bounds checks

The column is nullable=False with a server_default so it applies cleanly
to existing rows with no data migration required.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0095_mvp6_semantic_qa_grounding"
down_revision: Union[str, None] = "0094_mvp1_extraction_schema_agnosticism"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "qa_score_records",
        sa.Column(
            "semantic_grounding",
            sa.Float(),
            nullable=False,
            server_default=sa.text("0.0"),
        ),
        schema="public",
    )
    op.create_check_constraint(
        "semantic_grounding_bounds",
        "qa_score_records",
        "semantic_grounding >= 0 AND semantic_grounding <= 1",
        schema="public",
    )


def downgrade() -> None:
    op.drop_constraint(
        "semantic_grounding_bounds",
        "qa_score_records",
        type_="check",
        schema="public",
    )
    op.drop_column("qa_score_records", "semantic_grounding", schema="public")
