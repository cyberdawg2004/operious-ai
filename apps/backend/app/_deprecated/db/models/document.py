"""Document persistence.

One row per ingested document. The `content_hash` column is the
dedup key: identical (source, content_hash) means the same document
content; ingestion can skip work, or treat re-ingestion as an update.

`request_id` is captured at ingestion time so the entire pipeline
that produced this row can be replayed from logs.

Sister tables (`document_chunks`, `chunk_embeddings`) reference this
via FK with `ON DELETE CASCADE` so removing a document clears all
derived rows.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Document(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Operational record of one ingested document."""

    __tablename__ = "documents"

    source: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    content: Mapped[str] = mapped_column(String, nullable=False)
    content_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    request_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)


__all__ = ["Document"]
