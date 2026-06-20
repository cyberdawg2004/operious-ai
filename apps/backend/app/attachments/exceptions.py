"""Attachment-domain exceptions."""

from __future__ import annotations


class AttachmentNotFoundError(LookupError):
    """Raised when no stored attachment matches the given id + tenant_id."""


class AttachmentPersistenceError(RuntimeError):
    """Raised when an attachment metadata row could not be persisted."""
