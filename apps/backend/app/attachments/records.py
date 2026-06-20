"""In-memory representation of a tenant_attachments row."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.attachments.identity import AttachmentId


@dataclass(frozen=True, slots=True)
class AttachmentRecord:
    attachment_id: AttachmentId
    tenant_id: str
    channel: str
    external_message_id: str | None
    conversation_id: str | None
    storage_backend: str
    storage_key: str | None
    content_type_declared: str | None
    content_type_sniffed: str | None
    size_bytes: int
    sha256_digest: str
    status: str
    rejection_reason: str | None
    created_at: datetime
    retention_expires_at: datetime | None
    # Populated only by AttachmentRepository.get() — decrypted plaintext.
    # Never set on the records returned by store()'s metadata-row insert.
    content: bytes | None = None
