"""promote knowledge native embeddings to 1536 dimensions

Revision ID: 0075_knowledge_embeddings_1536
Revises: 0074_work_order_dispatch_substrate
Create Date: 2026-06-05
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0075_knowledge_embeddings_1536"
down_revision: Union[str, None] = "0074_work_order_dispatch_substrate"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "tenant_knowledge_vectors"
_INDEX = "ix_tenant_knowledge_vectors_embedding_hnsw"
_TARGET_DIMENSIONS = 1536
_LEGACY_DIMENSIONS = 32


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(f"DROP INDEX IF EXISTS public.{_INDEX}")
    op.execute(f"ALTER TABLE public.{_TABLE} DROP COLUMN IF EXISTS embedding")
    op.execute(
        f"""
        ALTER TABLE public.{_TABLE}
        ADD COLUMN embedding vector({_TARGET_DIMENSIONS})
        """
    )
    op.execute(
        f"""
        UPDATE public.{_TABLE}
        SET embedding = CAST(vector AS text)::vector({_TARGET_DIMENSIONS})
        WHERE vector IS NOT NULL
          AND dimensions = {_TARGET_DIMENSIONS}
        """
    )
    op.execute(
        f"""
        CREATE INDEX IF NOT EXISTS {_INDEX}
        ON public.{_TABLE}
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
        """
    )
    _force_rls()


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS public.{_INDEX}")
    op.execute(f"ALTER TABLE public.{_TABLE} DROP COLUMN IF EXISTS embedding")
    op.execute(
        f"""
        ALTER TABLE public.{_TABLE}
        ADD COLUMN embedding vector({_LEGACY_DIMENSIONS})
        """
    )
    op.execute(
        f"""
        UPDATE public.{_TABLE}
        SET embedding = CAST(vector AS text)::vector({_LEGACY_DIMENSIONS})
        WHERE vector IS NOT NULL
          AND dimensions = {_LEGACY_DIMENSIONS}
        """
    )
    op.execute(
        f"""
        CREATE INDEX IF NOT EXISTS {_INDEX}
        ON public.{_TABLE}
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
        """
    )
    _force_rls()


def _force_rls() -> None:
    op.execute(f"ALTER TABLE public.{_TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE public.{_TABLE} FORCE ROW LEVEL SECURITY")
