"""Document-chunk persistence access.

Persistence-only. Bulk insert via `add_all` so a multi-chunk document
ingests in a single round-trip.
"""

from __future__ import annotations

import uuid
from typing import Iterable, Sequence

from sqlalchemy import select

from app._deprecated.db.models.document_chunk import DocumentChunk
from app.repositories.base import BaseRepository


class DocumentChunkRepository(BaseRepository):
    """Persistence access for `document_chunks`."""

    async def create_chunks(
        self,
        chunks: Iterable[DocumentChunk],
    ) -> list[DocumentChunk]:
        items = list(chunks)
        if not items:
            return []
        self.session.add_all(items)
        await self.session.flush()
        return items

    async def for_document(
        self,
        document_id: uuid.UUID,
    ) -> Sequence[DocumentChunk]:
        stmt = (
            select(DocumentChunk)
            .where(DocumentChunk.document_id == document_id)
            .order_by(DocumentChunk.ordinal)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def by_ids(
        self,
        chunk_ids: Sequence[uuid.UUID],
    ) -> Sequence[DocumentChunk]:
        if not chunk_ids:
            return ()
        stmt = select(DocumentChunk).where(DocumentChunk.id.in_(chunk_ids))
        result = await self.session.execute(stmt)
        return result.scalars().all()


__all__ = ["DocumentChunkRepository"]
