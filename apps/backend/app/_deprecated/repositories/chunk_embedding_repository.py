"""Chunk-embedding registration persistence.

Persistence-only. These rows are bookkeeping — they record that a
given chunk has been embedded by a particular provider/model and
registered in a specific vector index under a specific vector id.

The unique constraint `(chunk_id, provider, model, vector_index_name)`
is what makes ingestion idempotent: replays insert no duplicates.
"""

from __future__ import annotations

import uuid
from typing import Iterable, Sequence

from sqlalchemy import select

from app._deprecated.db.models.chunk_embedding import ChunkEmbedding
from app.repositories.base import BaseRepository


class ChunkEmbeddingRepository(BaseRepository):
    """Persistence access for `chunk_embeddings`."""

    async def create_embeddings(
        self,
        embeddings: Iterable[ChunkEmbedding],
    ) -> list[ChunkEmbedding]:
        items = list(embeddings)
        if not items:
            return []
        self.session.add_all(items)
        await self.session.flush()
        return items

    async def for_chunk(
        self,
        chunk_id: uuid.UUID,
    ) -> Sequence[ChunkEmbedding]:
        stmt = select(ChunkEmbedding).where(ChunkEmbedding.chunk_id == chunk_id)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def exists(
        self,
        *,
        chunk_id: uuid.UUID,
        provider: str,
        model: str,
        vector_index_name: str,
    ) -> bool:
        stmt = (
            select(ChunkEmbedding.id)
            .where(ChunkEmbedding.chunk_id == chunk_id)
            .where(ChunkEmbedding.provider == provider)
            .where(ChunkEmbedding.model == model)
            .where(ChunkEmbedding.vector_index_name == vector_index_name)
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None


__all__ = ["ChunkEmbeddingRepository"]
