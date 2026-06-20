"""Customer attachment storage (Phase B1a).

Foundation only: a tenant-isolated, encrypted-at-rest store for
customer-submitted evidence (invoice/receipt photos, PDFs) arriving over
email/WhatsApp. This package does NOT wire up email or WhatsApp ingestion
(PR-B1b/B1.5) — it only provides the storage primitive those paths and the
B2/B3 vision/extraction work will call.
"""

from __future__ import annotations

from app.attachments.exceptions import (
    AttachmentNotFoundError,
    AttachmentPersistenceError,
)
from app.attachments.identity import AttachmentId
from app.attachments.records import AttachmentRecord
from app.attachments.repository import AttachmentRepository
from app.attachments.s3_client import AttachmentBlobStore
from app.attachments.sniffing import ATTACHMENT_ALLOWED_CONTENT_TYPES, AttachmentTypeError
from app.attachments.storage_service import AttachmentStorageService
from app.attachments.streaming import AttachmentTooLargeError

__all__ = [
    "ATTACHMENT_ALLOWED_CONTENT_TYPES",
    "AttachmentBlobStore",
    "AttachmentId",
    "AttachmentNotFoundError",
    "AttachmentPersistenceError",
    "AttachmentRecord",
    "AttachmentRepository",
    "AttachmentStorageService",
    "AttachmentTooLargeError",
    "AttachmentTypeError",
]
