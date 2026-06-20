"""ORM row for ``tenant_attachments``."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import TENANT_ID_MAX_LENGTH, Base

_CHANNEL_WIDTH = 32
_STORAGE_BACKEND_WIDTH = 16
_STATUS_WIDTH = 16
_CONTENT_TYPE_WIDTH = 128
_STORAGE_KEY_WIDTH = 512
_EXTERNAL_ID_WIDTH = 255
_SHA256_HEX_WIDTH = 64


class TenantAttachmentRow(Base):
    """ORM row for ``tenant_attachments``.

    Binaries never live in this table — ``storage_key`` is a reference
    into S3; the row holds metadata only. See
    ``app.attachments.storage_service.AttachmentStorageService`` for the
    write path and ``app.attachments.repository.AttachmentRepository``
    for the retrieval interface.
    """

    __tablename__ = "tenant_attachments"

    attachment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
    )
    tenant_id: Mapped[str] = mapped_column(
        String(TENANT_ID_MAX_LENGTH),
        ForeignKey("tenants.tenant_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    channel: Mapped[str] = mapped_column(String(_CHANNEL_WIDTH), nullable=False)
    external_message_id: Mapped[str | None] = mapped_column(
        String(_EXTERNAL_ID_WIDTH), nullable=True
    )
    conversation_id: Mapped[str | None] = mapped_column(
        String(_EXTERNAL_ID_WIDTH), nullable=True
    )
    storage_backend: Mapped[str] = mapped_column(
        String(_STORAGE_BACKEND_WIDTH),
        nullable=False,
        server_default=text("'s3'"),
    )
    storage_key: Mapped[str | None] = mapped_column(
        String(_STORAGE_KEY_WIDTH), nullable=True
    )
    content_type_declared: Mapped[str | None] = mapped_column(
        String(_CONTENT_TYPE_WIDTH), nullable=True
    )
    content_type_sniffed: Mapped[str | None] = mapped_column(
        String(_CONTENT_TYPE_WIDTH), nullable=True
    )
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256_digest: Mapped[str] = mapped_column(
        String(_SHA256_HEX_WIDTH), nullable=False
    )
    status: Mapped[str] = mapped_column(String(_STATUS_WIDTH), nullable=False)
    rejection_reason: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    retention_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        CheckConstraint("length(tenant_id) > 0", name="tenant_id_nonempty"),
        CheckConstraint(
            "size_bytes >= 0", name="ck_tenant_attachments_size_bytes_nonnegative"
        ),
        CheckConstraint(
            "channel IN ('email', 'whatsapp')",
            name="ck_tenant_attachments_channel_valid",
        ),
        CheckConstraint(
            "storage_backend IN ('s3', 'postgres')",
            name="ck_tenant_attachments_storage_backend_valid",
        ),
        CheckConstraint(
            "status IN ('stored', 'rejected')",
            name="ck_tenant_attachments_status_valid",
        ),
        CheckConstraint(
            "(status = 'stored' AND storage_key IS NOT NULL) "
            "OR (status = 'rejected' AND storage_key IS NULL)",
            name="ck_tenant_attachments_storage_key_matches_status",
        ),
        Index(
            "ix_tenant_attachments_tenant_status",
            "tenant_id",
            "status",
        ),
        Index(
            "ix_tenant_attachments_tenant_message",
            "tenant_id",
            "external_message_id",
        ),
    )
