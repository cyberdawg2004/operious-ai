"""SOP intelligence ORM rows."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TENANT_ID_MAX_LENGTH

_STATUS_WIDTH = 32
_HANDLE_WIDTH = 255


class ApprovalRecordRow(Base):
    """ORM row for ``approval_records``."""

    __tablename__ = "approval_records"

    approval_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True
    )
    tenant_id: Mapped[str] = mapped_column(
        String(TENANT_ID_MAX_LENGTH),
        ForeignKey("tenants.tenant_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenant_knowledge_documents.document_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    proposed_change: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_sessions: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(
        String(_STATUS_WIDTH), nullable=False, index=True
    )
    proposed_by: Mapped[str] = mapped_column(
        String(_HANDLE_WIDTH), nullable=False
    )
    reviewed_by: Mapped[str | None] = mapped_column(
        String(_HANDLE_WIDTH), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )

    __table_args__ = (
        CheckConstraint("length(tenant_id) > 0", name="tenant_id_nonempty"),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="approval_confidence_bounds",
        ),
        CheckConstraint(
            "status IN ('pending_review', 'approved', 'rejected', 'applied')",
            name="approval_status_valid",
        ),
        Index(
            "ix_approval_records_tenant_status",
            "tenant_id",
            "status",
        ),
        Index(
            "ix_approval_records_tenant_created",
            "tenant_id",
            "created_at",
        ),
    )


__all__ = ["ApprovalRecordRow"]
