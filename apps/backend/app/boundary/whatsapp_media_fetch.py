"""Durable side-channel for the B1.5 Meta WhatsApp media two-hop fetch.

boundary_ingress / coordination_envelopes are write-once end to end (see
app.boundary.ingress.runtime, app.services.dispatch_service) — there is
no mutable "ticket" row a background task could patch once a media id
is captured at webhook time. This table is that mutable side-channel:

* The webhook writes a ``pending`` row immediately (durable — a media
  id is never lost even if the fetch task fails to enqueue).
* A background Celery task (app.workers.whatsapp_media_fetch_tasks)
  resolves it to ``stored`` (with the resulting attachment_id) or
  ``failed`` once its bounded retry budget is exhausted.
* ``DispatchService`` (app.services.dispatch_service) reads resolved
  rows by ``ingress_id`` to fold the final attachment state into the
  coordination envelope at the one point it is still being written
  for the first time.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import StrEnum
from typing import Protocol, cast

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import CursorResult

from app.boundary.db.models import WhatsAppMediaFetchRecordRow
from app.repositories.base import BaseRepository

_FETCH_NAMESPACE = uuid.UUID("7d4f9c5e-0e3a-4b8e-9b1a-3c4f2a6d8e10")


def _derive_fetch_id(*, tenant_id: str, ingress_id: uuid.UUID, media_id: str) -> uuid.UUID:
    """Deterministic, not random — derived from the same natural key the
    UNIQUE constraint enforces (tenant_id, ingress_id, media_id), so a
    retried/duplicate create_pending() call is naturally idempotent."""
    return uuid.uuid5(_FETCH_NAMESPACE, f"{tenant_id}|{ingress_id}|{media_id}")


class WhatsAppMediaFetchStatus(StrEnum):
    PENDING = "pending"
    STORED = "stored"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class WhatsAppMediaFetchRecord:
    fetch_id: uuid.UUID
    tenant_id: str
    ingress_id: uuid.UUID
    external_message_id: str
    media_id: str
    status: WhatsAppMediaFetchStatus
    created_at: datetime
    mime_type: str | None = None
    attachment_id: uuid.UUID | None = None
    attempt_count: int = 0
    last_error: str | None = None
    resolved_at: datetime | None = None

    @property
    def is_terminal(self) -> bool:
        return self.status is not WhatsAppMediaFetchStatus.PENDING


class WhatsAppMediaFetchRepositoryProtocol(Protocol):
    async def create_pending(
        self,
        *,
        tenant_id: str,
        ingress_id: uuid.UUID,
        external_message_id: str,
        media_id: str,
        mime_type: str | None,
        created_at: datetime | None = None,
    ) -> WhatsAppMediaFetchRecord: ...

    async def get(
        self,
        fetch_id: uuid.UUID,
        *,
        tenant_id: str,
    ) -> WhatsAppMediaFetchRecord | None: ...

    async def list_by_ingress(
        self,
        ingress_id: uuid.UUID,
        *,
        tenant_id: str,
    ) -> tuple[WhatsAppMediaFetchRecord, ...]: ...

    async def increment_attempt(
        self,
        fetch_id: uuid.UUID,
        *,
        tenant_id: str,
    ) -> WhatsAppMediaFetchRecord | None: ...

    async def mark_stored(
        self,
        fetch_id: uuid.UUID,
        *,
        tenant_id: str,
        attachment_id: uuid.UUID,
        resolved_at: datetime | None = None,
    ) -> WhatsAppMediaFetchRecord | None: ...

    async def mark_failed(
        self,
        fetch_id: uuid.UUID,
        *,
        tenant_id: str,
        error: str,
        resolved_at: datetime | None = None,
    ) -> WhatsAppMediaFetchRecord | None: ...

    async def list_stale_pending(
        self,
        *,
        stale_before: datetime,
        limit: int = 100,
    ) -> tuple[WhatsAppMediaFetchRecord, ...]: ...


class PostgresWhatsAppMediaFetchPersistence(BaseRepository):
    """Postgres implementation of :class:`WhatsAppMediaFetchRepositoryProtocol`."""

    async def create_pending(
        self,
        *,
        tenant_id: str,
        ingress_id: uuid.UUID,
        external_message_id: str,
        media_id: str,
        mime_type: str | None,
        created_at: datetime | None = None,
    ) -> WhatsAppMediaFetchRecord:
        ts = created_at or datetime.now(tz=timezone.utc)
        stmt = (
            pg_insert(WhatsAppMediaFetchRecordRow)
            .values(
                fetch_id=_derive_fetch_id(
                    tenant_id=tenant_id, ingress_id=ingress_id, media_id=media_id
                ),
                tenant_id=tenant_id,
                ingress_id=ingress_id,
                external_message_id=external_message_id,
                media_id=media_id,
                mime_type=mime_type,
                status=WhatsAppMediaFetchStatus.PENDING.value,
                attempt_count=0,
                created_at=ts,
            )
            .on_conflict_do_nothing(
                index_elements=["tenant_id", "ingress_id", "media_id"]
            )
            .returning(WhatsAppMediaFetchRecordRow)
        )
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        if row is not None:
            return _row_to_record(row)
        existing = await self._get_by_natural_key(
            tenant_id=tenant_id, ingress_id=ingress_id, media_id=media_id
        )
        if existing is None:
            raise RuntimeError(
                "whatsapp media fetch insert conflicted but no row found"
            )
        return existing

    async def _get_by_natural_key(
        self,
        *,
        tenant_id: str,
        ingress_id: uuid.UUID,
        media_id: str,
    ) -> WhatsAppMediaFetchRecord | None:
        stmt = select(WhatsAppMediaFetchRecordRow).where(
            WhatsAppMediaFetchRecordRow.tenant_id == tenant_id,
            WhatsAppMediaFetchRecordRow.ingress_id == ingress_id,
            WhatsAppMediaFetchRecordRow.media_id == media_id,
        )
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        return None if row is None else _row_to_record(row)

    async def get(
        self,
        fetch_id: uuid.UUID,
        *,
        tenant_id: str,
    ) -> WhatsAppMediaFetchRecord | None:
        stmt = select(WhatsAppMediaFetchRecordRow).where(
            WhatsAppMediaFetchRecordRow.fetch_id == fetch_id,
            WhatsAppMediaFetchRecordRow.tenant_id == tenant_id,
        )
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        return None if row is None else _row_to_record(row)

    async def list_by_ingress(
        self,
        ingress_id: uuid.UUID,
        *,
        tenant_id: str,
    ) -> tuple[WhatsAppMediaFetchRecord, ...]:
        stmt = select(WhatsAppMediaFetchRecordRow).where(
            WhatsAppMediaFetchRecordRow.ingress_id == ingress_id,
            WhatsAppMediaFetchRecordRow.tenant_id == tenant_id,
        )
        rows = (await self.session.execute(stmt)).scalars().all()  # bounded per ingress
        return tuple(_row_to_record(row) for row in rows)

    async def increment_attempt(
        self,
        fetch_id: uuid.UUID,
        *,
        tenant_id: str,
    ) -> WhatsAppMediaFetchRecord | None:
        stmt = (
            update(WhatsAppMediaFetchRecordRow)
            .where(
                WhatsAppMediaFetchRecordRow.fetch_id == fetch_id,
                WhatsAppMediaFetchRecordRow.tenant_id == tenant_id,
                WhatsAppMediaFetchRecordRow.status
                == WhatsAppMediaFetchStatus.PENDING.value,
            )
            .values(
                attempt_count=WhatsAppMediaFetchRecordRow.attempt_count + 1,
            )
        )
        result = cast(CursorResult[object], await self.session.execute(stmt))
        if result.rowcount != 1:
            return None
        return await self.get(fetch_id, tenant_id=tenant_id)

    async def mark_stored(
        self,
        fetch_id: uuid.UUID,
        *,
        tenant_id: str,
        attachment_id: uuid.UUID,
        resolved_at: datetime | None = None,
    ) -> WhatsAppMediaFetchRecord | None:
        ts = resolved_at or datetime.now(tz=timezone.utc)
        stmt = (
            update(WhatsAppMediaFetchRecordRow)
            .where(
                WhatsAppMediaFetchRecordRow.fetch_id == fetch_id,
                WhatsAppMediaFetchRecordRow.tenant_id == tenant_id,
                WhatsAppMediaFetchRecordRow.status
                == WhatsAppMediaFetchStatus.PENDING.value,
            )
            .values(
                status=WhatsAppMediaFetchStatus.STORED.value,
                attachment_id=attachment_id,
                last_error=None,
                resolved_at=ts,
            )
        )
        result = cast(CursorResult[object], await self.session.execute(stmt))
        if result.rowcount != 1:
            return None
        return await self.get(fetch_id, tenant_id=tenant_id)

    async def mark_failed(
        self,
        fetch_id: uuid.UUID,
        *,
        tenant_id: str,
        error: str,
        resolved_at: datetime | None = None,
    ) -> WhatsAppMediaFetchRecord | None:
        ts = resolved_at or datetime.now(tz=timezone.utc)
        stmt = (
            update(WhatsAppMediaFetchRecordRow)
            .where(
                WhatsAppMediaFetchRecordRow.fetch_id == fetch_id,
                WhatsAppMediaFetchRecordRow.tenant_id == tenant_id,
                WhatsAppMediaFetchRecordRow.status
                == WhatsAppMediaFetchStatus.PENDING.value,
            )
            .values(
                status=WhatsAppMediaFetchStatus.FAILED.value,
                last_error=error[:2000],
                resolved_at=ts,
            )
        )
        result = cast(CursorResult[object], await self.session.execute(stmt))
        if result.rowcount != 1:
            return None
        return await self.get(fetch_id, tenant_id=tenant_id)

    async def list_stale_pending(
        self,
        *,
        stale_before: datetime,
        limit: int = 100,
    ) -> tuple[WhatsAppMediaFetchRecord, ...]:
        # PRIVILEGED_PATH: cross-tenant maintenance sweep, owner session only.
        stmt = (
            select(WhatsAppMediaFetchRecordRow)
            .where(
                WhatsAppMediaFetchRecordRow.status
                == WhatsAppMediaFetchStatus.PENDING.value,
                WhatsAppMediaFetchRecordRow.created_at <= stale_before,
            )
            .order_by(WhatsAppMediaFetchRecordRow.created_at)
            .limit(limit)
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return tuple(_row_to_record(row) for row in rows)


def _row_to_record(row: WhatsAppMediaFetchRecordRow) -> WhatsAppMediaFetchRecord:
    return WhatsAppMediaFetchRecord(
        fetch_id=row.fetch_id,
        tenant_id=row.tenant_id,
        ingress_id=row.ingress_id,
        external_message_id=row.external_message_id,
        media_id=row.media_id,
        mime_type=row.mime_type,
        status=WhatsAppMediaFetchStatus(row.status),
        attachment_id=row.attachment_id,
        attempt_count=row.attempt_count,
        last_error=row.last_error,
        created_at=row.created_at,
        resolved_at=row.resolved_at,
    )


class InMemoryWhatsAppMediaFetchPersistence:
    """Deterministic in-memory implementation for unit tests."""

    def __init__(self) -> None:
        self._rows: dict[uuid.UUID, WhatsAppMediaFetchRecord] = {}

    async def create_pending(
        self,
        *,
        tenant_id: str,
        ingress_id: uuid.UUID,
        external_message_id: str,
        media_id: str,
        mime_type: str | None,
        created_at: datetime | None = None,
    ) -> WhatsAppMediaFetchRecord:
        for existing in self._rows.values():
            if (
                existing.tenant_id == tenant_id
                and existing.ingress_id == ingress_id
                and existing.media_id == media_id
            ):
                return existing
        record = WhatsAppMediaFetchRecord(
            fetch_id=_derive_fetch_id(
                tenant_id=tenant_id, ingress_id=ingress_id, media_id=media_id
            ),
            tenant_id=tenant_id,
            ingress_id=ingress_id,
            external_message_id=external_message_id,
            media_id=media_id,
            mime_type=mime_type,
            status=WhatsAppMediaFetchStatus.PENDING,
            created_at=created_at or datetime.now(tz=timezone.utc),
        )
        self._rows[record.fetch_id] = record
        return record

    async def get(
        self,
        fetch_id: uuid.UUID,
        *,
        tenant_id: str,
    ) -> WhatsAppMediaFetchRecord | None:
        record = self._rows.get(fetch_id)
        if record is None or record.tenant_id != tenant_id:
            return None
        return record

    async def list_by_ingress(
        self,
        ingress_id: uuid.UUID,
        *,
        tenant_id: str,
    ) -> tuple[WhatsAppMediaFetchRecord, ...]:
        return tuple(
            record
            for record in self._rows.values()
            if record.ingress_id == ingress_id and record.tenant_id == tenant_id
        )

    async def increment_attempt(
        self,
        fetch_id: uuid.UUID,
        *,
        tenant_id: str,
    ) -> WhatsAppMediaFetchRecord | None:
        record = await self.get(fetch_id, tenant_id=tenant_id)
        if record is None or record.is_terminal:
            return None
        updated = replace(record, attempt_count=record.attempt_count + 1)
        self._rows[fetch_id] = updated
        return updated

    async def mark_stored(
        self,
        fetch_id: uuid.UUID,
        *,
        tenant_id: str,
        attachment_id: uuid.UUID,
        resolved_at: datetime | None = None,
    ) -> WhatsAppMediaFetchRecord | None:
        record = await self.get(fetch_id, tenant_id=tenant_id)
        if record is None or record.is_terminal:
            return None
        updated = replace(
            record,
            status=WhatsAppMediaFetchStatus.STORED,
            attachment_id=attachment_id,
            last_error=None,
            resolved_at=resolved_at or datetime.now(tz=timezone.utc),
        )
        self._rows[fetch_id] = updated
        return updated

    async def mark_failed(
        self,
        fetch_id: uuid.UUID,
        *,
        tenant_id: str,
        error: str,
        resolved_at: datetime | None = None,
    ) -> WhatsAppMediaFetchRecord | None:
        record = await self.get(fetch_id, tenant_id=tenant_id)
        if record is None or record.is_terminal:
            return None
        updated = replace(
            record,
            status=WhatsAppMediaFetchStatus.FAILED,
            last_error=error[:2000],
            resolved_at=resolved_at or datetime.now(tz=timezone.utc),
        )
        self._rows[fetch_id] = updated
        return updated

    async def list_stale_pending(
        self,
        *,
        stale_before: datetime,
        limit: int = 100,
    ) -> tuple[WhatsAppMediaFetchRecord, ...]:
        pending = sorted(
            (
                record
                for record in self._rows.values()
                if record.status is WhatsAppMediaFetchStatus.PENDING
                and record.created_at <= stale_before
            ),
            key=lambda record: record.created_at,
        )
        return tuple(pending[:limit])


__all__ = [
    "InMemoryWhatsAppMediaFetchPersistence",
    "PostgresWhatsAppMediaFetchPersistence",
    "WhatsAppMediaFetchRecord",
    "WhatsAppMediaFetchRepositoryProtocol",
    "WhatsAppMediaFetchStatus",
]
