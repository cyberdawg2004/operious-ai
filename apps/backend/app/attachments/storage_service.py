"""Attachment ingestion entrypoint: bound -> sniff -> encrypt -> S3 -> row.

This is the ONLY way bytes are accepted into attachment storage. Ordering
matches ``app.tenant.file_ingestion``'s precedent: the size cap is enforced
streaming-first (see ``app.attachments.streaming.read_bounded``), magic-byte
sniffing is authoritative over any declared Content-Type, and no parser or
downstream consumer ever touches content before both checks pass.

A rejection (oversized or wrong type) never reaches S3 — it is recorded as
a ``status='rejected'`` metadata row with no ``storage_key``, matching the
CHECK constraint on ``tenant_attachments``.
"""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from collections.abc import Iterable

from app.attachments.records import AttachmentRecord
from app.attachments.repository import AttachmentRepository
from app.attachments.s3_client import AttachmentBlobStore
from app.attachments.sniffing import AttachmentTypeError, sniff_attachment_content_type
from app.attachments.streaming import AttachmentTooLargeError, read_bounded
from app.core.config import Settings
from app.data_protection.crypto import DataProtectionService


class AttachmentStorageService:
    __slots__ = (
        "_repository",
        "_blob_store",
        "_data_protection",
        "_max_bytes",
        "_retention_days",
    )

    def __init__(
        self,
        *,
        repository: AttachmentRepository,
        blob_store: AttachmentBlobStore,
        data_protection: DataProtectionService,
        max_bytes: int,
        retention_days: int,
    ) -> None:
        self._repository = repository
        self._blob_store = blob_store
        self._data_protection = data_protection
        self._max_bytes = max_bytes
        self._retention_days = retention_days

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        *,
        repository: AttachmentRepository,
        blob_store: AttachmentBlobStore,
        data_protection: DataProtectionService,
    ) -> "AttachmentStorageService":
        return cls(
            repository=repository,
            blob_store=blob_store,
            data_protection=data_protection,
            max_bytes=settings.ATTACHMENT_MAX_BYTES,
            retention_days=settings.ATTACHMENT_RETENTION_DAYS,
        )

    async def store(
        self,
        chunks: Iterable[bytes],
        *,
        tenant_id: str,
        channel: str,
        external_message_id: str | None = None,
        conversation_id: str | None = None,
        content_type_declared: str | None = None,
    ) -> AttachmentRecord:
        # Generated client-side (not gen_random_uuid() server-side)
        # because the same id is needed before the INSERT to build the S3
        # storage_key below.
        attachment_id = uuid.uuid4()  # APPROVED_EXCEPTION: pre-insert S3 key

        try:
            raw = read_bounded(chunks, max_bytes=self._max_bytes)
        except AttachmentTooLargeError as exc:
            return await self._repository.insert_rejected(
                attachment_id=attachment_id,
                tenant_id=tenant_id,
                channel=channel,
                external_message_id=external_message_id,
                conversation_id=conversation_id,
                content_type_declared=content_type_declared,
                size_bytes=exc.bytes_read,
                sha256_digest="",
                rejection_reason=str(exc),
            )

        digest = hashlib.sha256(raw).hexdigest()

        try:
            sniffed_type = sniff_attachment_content_type(raw)
        except AttachmentTypeError as exc:
            return await self._repository.insert_rejected(
                attachment_id=attachment_id,
                tenant_id=tenant_id,
                channel=channel,
                external_message_id=external_message_id,
                conversation_id=conversation_id,
                content_type_declared=content_type_declared,
                size_bytes=len(raw),
                sha256_digest=digest,
                rejection_reason=str(exc),
            )

        encrypted = await self._data_protection.encrypt_bytes(
            raw,
            tenant_id=tenant_id,
            subject_id=None,
            field="tenant_attachments.binary",
            tenant_scoped=True,
        )

        storage_key = f"{tenant_id}/{attachment_id}"
        await asyncio.to_thread(self._blob_store.put, storage_key, encrypted)

        return await self._repository.insert_stored(
            attachment_id=attachment_id,
            tenant_id=tenant_id,
            channel=channel,
            external_message_id=external_message_id,
            conversation_id=conversation_id,
            storage_key=storage_key,
            content_type_declared=content_type_declared,
            content_type_sniffed=sniffed_type,
            size_bytes=len(raw),
            sha256_digest=digest,
            retention_days=self._retention_days,
        )
