"""Attachment magic-byte validation.

Reuses app.tenant.file_ingestion's shared detector (the same primitive
that protects knowledge-base uploads) rather than re-implementing
magic-byte parsing — see detect_content_type() there. This module applies
a SEPARATE allow-list: customer attachments legitimately include receipt
photos, so JPEG/PNG are admitted here. The knowledge-upload allow-list is
intentionally NOT relaxed to admit images — that would let images leak
into the KB ingestion/RAG path, which is a different trust boundary.
"""

from __future__ import annotations

from app.tenant.file_ingestion import EXECUTABLE_CONTENT_TYPE, detect_content_type

ATTACHMENT_ALLOWED_CONTENT_TYPES: frozenset[str] = frozenset(
    {
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "image/jpeg",
        "image/png",
        "text/plain",
    }
)


class AttachmentTypeError(ValueError):
    """Raised when magic bytes do not match a supported attachment type."""


def sniff_attachment_content_type(raw: bytes) -> str:
    """Return a canonical MIME type, restricted to
    ``ATTACHMENT_ALLOWED_CONTENT_TYPES``. The caller's declared
    Content-Type is never consulted.
    """
    detected = detect_content_type(raw)
    if detected == EXECUTABLE_CONTENT_TYPE:
        raise AttachmentTypeError(
            "Executable binary rejected (MZ magic bytes detected)"
        )
    if detected is None or detected not in ATTACHMENT_ALLOWED_CONTENT_TYPES:
        raise AttachmentTypeError(
            "File does not match any supported attachment type "
            "(expected PDF, DOCX, JPEG, PNG, or UTF-8 plain text)"
        )
    return detected
