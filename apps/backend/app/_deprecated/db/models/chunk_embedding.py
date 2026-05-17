"""Chunk embedding registration.

One row per (chunk × embedding model × vector index) combination.
The actual vector lives in the configured `BaseVectorProvider`; this
row is the *bookkeeping* that says "this chunk has been embedded by
provider P with model M and is currently registered in vector index
I under vector-id V."

Why store this separately from the vector itself:

* lets us migrate vector stores (in-memory → pgvector → Pinecone)
  without losing track of what has been indexed,
* makes ingestion idempotent: skip re-embedding when a row exists
  for the same (chunk_id, provider, model, vector_index_name),
* keeps Postgres free of multi-thousand-dim arrays it would have to
  index but never query.

`vector_id` defaults to `chunk_id` in the Sprint G default flow but
the column is independent so providers that issue their own ids can
still be represented faithfully.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ChunkEmbedding(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One embedding registration for one chunk."""

    __tablename__ = "chunk_embeddings"
    __table_args__ = (
        UniqueConstraint(
            "chunk_id",
            "provider",
            "model",
            "vector_index_name",
            name="uq_chunk_embeddings_chunk_id_provider_model_vector_index_name",
        ),
    )

    chunk_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("document_chunks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    model: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    vector_index_name: Mapped[str] = mapped_column(
        String(128), nullable=False, index=True
    )
    vector_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)


__all__ = ["ChunkEmbedding"]
