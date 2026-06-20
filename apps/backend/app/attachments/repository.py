"""Postgres + S3 repository for customer attachment binaries.

Read path mirrors ``PostgresTenantConfigurationRepository.get_knowledge_upload``
(app/tenant/persistence/postgres.py): RLS scopes the row at the DB layer via
the session's tenant context, and the explicit ``tenant_id`` WHERE clause is
defense in depth on top of that, not the only guard.

Write path mirrors ``save_knowledge_upload``'s encrypt-before-insert
ordering, reusing the SAME ``DataProtectionService.encrypt_bytes`` /
``decrypt_bytes`` envelope (``tenant_scoped=True``) — no parallel crypto.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.attachments.db.models import TenantAttachmentRow
from app.attachments.exceptions import (
    AttachmentNotFoundError,
    AttachmentPersistenceError,
)
from app.attachments.identity import AttachmentId
from app.attachments.records import AttachmentRecord
from app.attachments.s3_client import AttachmentBlobStore
from app.data_protection.crypto import DataProtectionService
from app.repositories.base import BaseRepository

# Note on the clamp predicate: TenantAttachmentRow does not extend
# TenantScopedMixin (no substrate in this codebase actually does — see
# app.governance.persistence.postgres.PostgresGovernanceRepository's
# docstring), because the shared TenantScopedRepository._clamp_tenant
# helper is typed against that mixin and every adopter ends up inlining
# the equivalent predicate instead. Same SQL semantics, no fight with
# the type checker.


class AttachmentRepository(BaseRepository):
    """Metadata-row persistence plus the B2/B3 retrieval interface.

    ``get()`` is the ONLY read path exposed by this module: callers never
    receive a ``storage_key`` or presigned URL — only decrypted bytes,
    scoped by a mandatory ``tenant_id``. No presigned URL is ever issued.
    """

    __slots__ = ("_data_protection", "_blob_store")

    def __init__(
        self,
        session: AsyncSession,
        *,
        data_protection: DataProtectionService,
        blob_store: AttachmentBlobStore,
    ) -> None:
        super().__init__(session)
        self._data_protection = data_protection
        self._blob_store = blob_store

    async def insert_stored(
        self,
        *,
        attachment_id: uuid.UUID,
        tenant_id: str,
        channel: str,
        external_message_id: str | None,
        conversation_id: str | None,
        storage_key: str,
        content_type_declared: str | None,
        content_type_sniffed: str,
        size_bytes: int,
        sha256_digest: str,
        retention_days: int,
    ) -> AttachmentRecord:
        row = TenantAttachmentRow(
            attachment_id=attachment_id,
            tenant_id=tenant_id,
            channel=channel,
            external_message_id=external_message_id,
            conversation_id=conversation_id,
            storage_backend="s3",
            storage_key=storage_key,
            content_type_declared=content_type_declared,
            content_type_sniffed=content_type_sniffed,
            size_bytes=size_bytes,
            sha256_digest=sha256_digest,
            status="stored",
            rejection_reason=None,
            retention_expires_at=datetime.now(timezone.utc)
            + timedelta(days=retention_days),
        )
        await self._insert(row)
        return _row_to_record(row)

    async def insert_rejected(
        self,
        *,
        attachment_id: uuid.UUID,
        tenant_id: str,
        channel: str,
        external_message_id: str | None,
        conversation_id: str | None,
        content_type_declared: str | None,
        size_bytes: int,
        sha256_digest: str,
        rejection_reason: str,
    ) -> AttachmentRecord:
        row = TenantAttachmentRow(
            attachment_id=attachment_id,
            tenant_id=tenant_id,
            channel=channel,
            external_message_id=external_message_id,
            conversation_id=conversation_id,
            storage_backend="s3",
            storage_key=None,
            content_type_declared=content_type_declared,
            content_type_sniffed=None,
            size_bytes=size_bytes,
            sha256_digest=sha256_digest,
            status="rejected",
            rejection_reason=rejection_reason,
            retention_expires_at=None,
        )
        await self._insert(row)
        return _row_to_record(row)

    async def _insert(self, row: TenantAttachmentRow) -> None:
        try:
            async with self.session.begin_nested():
                self.session.add(row)
                await self.session.flush()
        except IntegrityError as exc:
            raise AttachmentPersistenceError(
                "attachment row could not be persisted"
            ) from exc

    async def get(
        self,
        attachment_id: AttachmentId,
        *,
        tenant_id: str,
    ) -> AttachmentRecord:
        """Fetch + decrypt an attachment. ``tenant_id`` is mandatory and is
        checked explicitly in addition to RLS — defense in depth, not the
        only guard (mirrors ``get_knowledge_upload``).
        """
        stmt = select(TenantAttachmentRow).where(
            TenantAttachmentRow.attachment_id == attachment_id,
            TenantAttachmentRow.tenant_id == tenant_id,
        )
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        if row is None or row.status != "stored" or row.storage_key is None:
            raise AttachmentNotFoundError(
                f"attachment {attachment_id} not found for tenant"
            )
        ciphertext = await asyncio.to_thread(self._blob_store.get, row.storage_key)
        plaintext = await self._data_protection.decrypt_bytes(ciphertext)
        return _row_to_record(row, content=plaintext)


def _row_to_record(
    row: TenantAttachmentRow, *, content: bytes | None = None
) -> AttachmentRecord:
    return AttachmentRecord(
        attachment_id=AttachmentId(row.attachment_id),
        tenant_id=row.tenant_id,
        channel=row.channel,
        external_message_id=row.external_message_id,
        conversation_id=row.conversation_id,
        storage_backend=row.storage_backend,
        storage_key=row.storage_key,
        content_type_declared=row.content_type_declared,
        content_type_sniffed=row.content_type_sniffed,
        size_bytes=row.size_bytes,
        sha256_digest=row.sha256_digest,
        status=row.status,
        rejection_reason=row.rejection_reason,
        created_at=row.created_at,
        retention_expires_at=row.retention_expires_at,
        content=content,
    )
