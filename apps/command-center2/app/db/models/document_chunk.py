"""Document chunk persistence.

One row per chunk produced by the chunking subsystem. References
`documents.id` via FK with `ON DELETE CASCADE`. `ordinal` is the
chunk's position within the document; `byte_start`/`byte_end` map
back to the original document text for context reconstruction.

`content_hash` exists at the chunk level too so re-chunking can
detect which chunks changed and re-embed only those.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class DocumentChunk(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One chunk of an ingested document."""

    __tablename__ = "document_chunks"

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(String, nullable=False)
    content_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )
    byte_start: Mapped[int] = mapped_column(Integer, nullable=False)
    byte_end: Mapped[int] = mapped_column(Integer, nullable=False)
    char_count: Mapped[int] = mapped_column(Integer, nullable=False)
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)


__all__ = ["DocumentChunk"]
