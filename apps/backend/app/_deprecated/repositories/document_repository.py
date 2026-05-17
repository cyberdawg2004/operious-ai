"""Document persistence access.

Persistence-only: query/insert/update by intent-named methods, never
commit, never rollback. The ingestion service owns the transaction.

Query surface is intentionally narrow:

* `find_by_content_hash` — ingestion idempotency check.
* `create_document`     — insert (returns the row).
* `update_chunk_count`  — service-driven, called once at end of pipeline.
* `get`                 — by id, for retrieval-side reads.
* `recent`              — for operational dashboards / debugging.
"""

from __future__ import annotations

import uuid
from typing import Any, Mapping, Sequence

from sqlalchemy import desc, select

from app._deprecated.db.models.document import Document
from app.repositories.base import BaseRepository


class DocumentRepository(BaseRepository):
    """Persistence access for `documents`."""

    async def find_by_content_hash(
        self,
        source: str,
        content_hash: str,
    ) -> Document | None:
        stmt = (
            select(Document)
            .where(Document.source == source)
            .where(Document.content_hash == content_hash)
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create_document(
        self,
        *,
        source: str,
        title: str | None,
        content: str,
        content_hash: str,
        request_id: str | None,
        meta: Mapping[str, Any] | None = None,
    ) -> Document:
        document = Document(
            source=source,
            title=title,
            content=content,
            content_hash=content_hash,
            chunk_count=0,
            request_id=request_id,
            meta=dict(meta) if meta else None,
        )
        self.session.add(document)
        await self.session.flush()
        return document

    async def update_chunk_count(
        self,
        document: Document,
        chunk_count: int,
    ) -> None:
        document.chunk_count = chunk_count
        await self.session.flush()

    async def get(self, document_id: uuid.UUID) -> Document | None:
        return await self.session.get(Document, document_id)

    async def recent(self, limit: int = 25) -> Sequence[Document]:
        stmt = (
            select(Document)
            .order_by(desc(Document.created_at))
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()


__all__ = ["DocumentRepository"]
