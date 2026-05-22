"""Tenant knowledge vector-store ORM rows."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TENANT_ID_MAX_LENGTH

_HANDLE_WIDTH = 255


class KnowledgeChunkRow(Base):
    """ORM row for ``tenant_knowledge_chunks``."""

    __tablename__ = "tenant_knowledge_chunks"

    chunk_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(TENANT_ID_MAX_LENGTH),
        ForeignKey("tenants.tenant_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenant_knowledge_documents.document_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_version: Mapped[int] = mapped_column(Integer, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    char_start: Mapped[int] = mapped_column(Integer, nullable=False)
    char_end: Mapped[int] = mapped_column(Integer, nullable=False)
    is_current: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )
    indexed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )

    __table_args__ = (
        CheckConstraint("length(tenant_id) > 0", name="tenant_id_nonempty"),
        CheckConstraint("document_version >= 1", name="document_version_positive"),
        CheckConstraint("ordinal >= 0", name="ordinal_nonnegative"),
        CheckConstraint("token_count >= 0", name="token_count_nonnegative"),
        CheckConstraint("char_start >= 0", name="char_start_nonnegative"),
        CheckConstraint("char_end >= char_start", name="char_span_valid"),
        UniqueConstraint(
            "tenant_id",
            "document_id",
            "document_version",
            "ordinal",
            name="uq_tenant_knowledge_chunks_document_version_ordinal",
        ),
        Index(
            "ix_tenant_knowledge_chunks_tenant_document_current",
            "tenant_id",
            "document_id",
            "is_current",
        ),
    )


class KnowledgeVectorRow(Base):
    """ORM row for ``tenant_knowledge_vectors``."""

    __tablename__ = "tenant_knowledge_vectors"

    vector_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(TENANT_ID_MAX_LENGTH),
        ForeignKey("tenants.tenant_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    chunk_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenant_knowledge_chunks.chunk_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenant_knowledge_documents.document_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_version: Mapped[int] = mapped_column(Integer, nullable=False)
    provider: Mapped[str] = mapped_column(String(_HANDLE_WIDTH), nullable=False)
    model: Mapped[str] = mapped_column(String(_HANDLE_WIDTH), nullable=False)
    dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    vector_index_name: Mapped[str] = mapped_column(
        String(_HANDLE_WIDTH),
        nullable=False,
        index=True,
    )
    vector: Mapped[list[float]] = mapped_column(JSONB, nullable=False)
    is_current: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )
    indexed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )

    __table_args__ = (
        CheckConstraint("length(tenant_id) > 0", name="tenant_id_nonempty"),
        CheckConstraint("document_version >= 1", name="document_version_positive"),
        CheckConstraint("dimensions > 0", name="dimensions_positive"),
        UniqueConstraint(
            "tenant_id",
            "chunk_id",
            "provider",
            "model",
            "vector_index_name",
            name="uq_tenant_knowledge_vectors_chunk_provider_model_index",
        ),
        Index(
            "ix_tenant_knowledge_vectors_tenant_index_current",
            "tenant_id",
            "vector_index_name",
            "is_current",
        ),
    )


__all__ = [
    "KnowledgeChunkRow",
    "KnowledgeVectorRow",
]
