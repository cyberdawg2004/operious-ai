"""Install pgvector extension and native knowledge vector column.

Revision ID: 0040_pgvector
Revises: 0039_dlq_replay_cols
Create Date: 2026-05-26
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "0040_pgvector"
down_revision: Union[str, None] = "0039_dlq_replay_cols"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.execute(
        """
        ALTER TABLE tenant_knowledge_vectors
        ADD COLUMN IF NOT EXISTS embedding vector(32)
        """
    )

    op.execute(
        """
        UPDATE tenant_knowledge_vectors
        SET embedding = CAST(vector AS text)::vector(32)
        WHERE vector IS NOT NULL
          AND embedding IS NULL
        """
    )

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS
        ix_tenant_knowledge_vectors_embedding_hnsw
        ON tenant_knowledge_vectors
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS
        ix_tenant_knowledge_vectors_embedding_hnsw
        """
    )
    op.execute(
        """
        ALTER TABLE tenant_knowledge_vectors
        DROP COLUMN IF EXISTS embedding
        """
    )
