"""WhatsApp customer-reply delivery ledger."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Any, Mapping, Protocol, cast, runtime_checkable

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError

from app.boundary.db.models import WhatsAppCustomerReplyDeliveryRow
from app.repositories.base import BaseRepository

WhatsAppCustomerReplyDeliveryId = uuid.UUID

_WHATSAPP_CUSTOMER_REPLY_DELIVERY_NAMESPACE = uuid.UUID(
    "2b7b4f5a-0001-4b01-9001-000000000003"
)


class WhatsAppDeliveryStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class WhatsAppCustomerReplyDeliveryRecord:
    delivery_id: WhatsAppCustomerReplyDeliveryId
    tenant_id: str
    draft_id: uuid.UUID
    proposal_id: uuid.UUID
    governance_decision_id: uuid.UUID
    phone_number_id: str
    recipient_phone_number: str
    draft_body_sha256: str
    status: WhatsAppDeliveryStatus
    provider_message_id: str | None
    provider_status_code: int | None
    error_code: str | None
    created_at: datetime
    updated_at: datetime
    sent_at: datetime | None
    metadata: Mapping[str, Any]


@runtime_checkable
class WhatsAppDeliveryRepository(Protocol):
    async def reserve_delivery(
        self,
        record: WhatsAppCustomerReplyDeliveryRecord,
        *,
        expected_tenant_id: str,
    ) -> tuple[WhatsAppCustomerReplyDeliveryRecord, bool]: ...

    async def get_delivery(
        self,
        delivery_id: WhatsAppCustomerReplyDeliveryId,
        *,
        expected_tenant_id: str,
    ) -> WhatsAppCustomerReplyDeliveryRecord | None: ...

    async def mark_sent(
        self,
        delivery_id: WhatsAppCustomerReplyDeliveryId,
        *,
        expected_tenant_id: str,
        provider_message_id: str,
        provider_status_code: int,
        sent_at: datetime,
    ) -> WhatsAppCustomerReplyDeliveryRecord: ...

    async def mark_failed(
        self,
        delivery_id: WhatsAppCustomerReplyDeliveryId,
        *,
        expected_tenant_id: str,
        error_code: str,
        failed_at: datetime,
        provider_status_code: int | None = None,
    ) -> WhatsAppCustomerReplyDeliveryRecord: ...


class PostgresWhatsAppDeliveryRepository(BaseRepository):
    """Postgres-backed WhatsApp delivery ledger."""

    async def reserve_delivery(
        self,
        record: WhatsAppCustomerReplyDeliveryRecord,
        *,
        expected_tenant_id: str,
    ) -> tuple[WhatsAppCustomerReplyDeliveryRecord, bool]:
        _assert_expected_tenant(record.tenant_id, expected_tenant_id)
        try:
            async with self.session.begin_nested():
                self.session.add(_record_to_row(record))
                await self.session.flush()
        except IntegrityError:
            existing = await self.get_delivery(
                record.delivery_id,
                expected_tenant_id=expected_tenant_id,
            )
            if existing is None:
                raise
            return existing, False
        return record, True

    async def get_delivery(
        self,
        delivery_id: WhatsAppCustomerReplyDeliveryId,
        *,
        expected_tenant_id: str,
    ) -> WhatsAppCustomerReplyDeliveryRecord | None:
        row = await self._delivery_row(
            delivery_id,
            expected_tenant_id=expected_tenant_id,
        )
        return None if row is None else _row_to_record(row)

    async def mark_sent(
        self,
        delivery_id: WhatsAppCustomerReplyDeliveryId,
        *,
        expected_tenant_id: str,
        provider_message_id: str,
        provider_status_code: int,
        sent_at: datetime,
    ) -> WhatsAppCustomerReplyDeliveryRecord:
        values = {
            "status": WhatsAppDeliveryStatus.SENT.value,
            "provider_message_id": provider_message_id,
            "provider_status_code": provider_status_code,
            "sent_at": sent_at,
            "updated_at": sent_at,
            "error_code": None,
        }
        return await self._update_delivery(
            delivery_id,
            expected_tenant_id=expected_tenant_id,
            values=values,
        )

    async def mark_failed(
        self,
        delivery_id: WhatsAppCustomerReplyDeliveryId,
        *,
        expected_tenant_id: str,
        error_code: str,
        failed_at: datetime,
        provider_status_code: int | None = None,
    ) -> WhatsAppCustomerReplyDeliveryRecord:
        values = {
            "status": WhatsAppDeliveryStatus.FAILED.value,
            "provider_status_code": provider_status_code,
            "updated_at": failed_at,
            "error_code": error_code,
        }
        return await self._update_delivery(
            delivery_id,
            expected_tenant_id=expected_tenant_id,
            values=values,
        )

    async def _update_delivery(
        self,
        delivery_id: WhatsAppCustomerReplyDeliveryId,
        *,
        expected_tenant_id: str,
        values: Mapping[str, Any],
    ) -> WhatsAppCustomerReplyDeliveryRecord:
        stmt = (
            update(WhatsAppCustomerReplyDeliveryRow)
            .where(
                WhatsAppCustomerReplyDeliveryRow.delivery_id == delivery_id,
                WhatsAppCustomerReplyDeliveryRow.tenant_id == expected_tenant_id,
            )
            .values(**dict(values))
        )
        result = cast(CursorResult[Any], await self.session.execute(stmt))
        if result.rowcount != 1:
            raise ValueError("whatsapp delivery not found")
        row = await self._delivery_row(
            delivery_id,
            expected_tenant_id=expected_tenant_id,
        )
        if row is None:
            raise ValueError("whatsapp delivery not found")
        return _row_to_record(row)

    async def _delivery_row(
        self,
        delivery_id: WhatsAppCustomerReplyDeliveryId,
        *,
        expected_tenant_id: str,
    ) -> WhatsAppCustomerReplyDeliveryRow | None:
        stmt = select(WhatsAppCustomerReplyDeliveryRow).where(
            WhatsAppCustomerReplyDeliveryRow.delivery_id == delivery_id,
            WhatsAppCustomerReplyDeliveryRow.tenant_id == expected_tenant_id,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()


class InMemoryWhatsAppDeliveryRepository:
    """In-memory WhatsApp delivery ledger for unit tests."""

    def __init__(self) -> None:
        self._records: dict[tuple[str, uuid.UUID], WhatsAppCustomerReplyDeliveryRecord]
        self._records = {}
        self._lock = asyncio.Lock()

    async def reserve_delivery(
        self,
        record: WhatsAppCustomerReplyDeliveryRecord,
        *,
        expected_tenant_id: str,
    ) -> tuple[WhatsAppCustomerReplyDeliveryRecord, bool]:
        _assert_expected_tenant(record.tenant_id, expected_tenant_id)
        key = (expected_tenant_id, record.delivery_id)
        async with self._lock:
            existing = self._records.get(key)
            if existing is not None:
                return existing, False
            self._records[key] = record
            return record, True

    async def get_delivery(
        self,
        delivery_id: WhatsAppCustomerReplyDeliveryId,
        *,
        expected_tenant_id: str,
    ) -> WhatsAppCustomerReplyDeliveryRecord | None:
        return self._records.get((expected_tenant_id, delivery_id))

    async def mark_sent(
        self,
        delivery_id: WhatsAppCustomerReplyDeliveryId,
        *,
        expected_tenant_id: str,
        provider_message_id: str,
        provider_status_code: int,
        sent_at: datetime,
    ) -> WhatsAppCustomerReplyDeliveryRecord:
        async with self._lock:
            record = self._require(delivery_id, expected_tenant_id)
            updated = replace(
                record,
                status=WhatsAppDeliveryStatus.SENT,
                provider_message_id=provider_message_id,
                provider_status_code=provider_status_code,
                error_code=None,
                sent_at=sent_at,
                updated_at=sent_at,
            )
            self._records[(expected_tenant_id, delivery_id)] = updated
            return updated

    async def mark_failed(
        self,
        delivery_id: WhatsAppCustomerReplyDeliveryId,
        *,
        expected_tenant_id: str,
        error_code: str,
        failed_at: datetime,
        provider_status_code: int | None = None,
    ) -> WhatsAppCustomerReplyDeliveryRecord:
        async with self._lock:
            record = self._require(delivery_id, expected_tenant_id)
            updated = replace(
                record,
                status=WhatsAppDeliveryStatus.FAILED,
                provider_status_code=provider_status_code,
                error_code=error_code,
                updated_at=failed_at,
            )
            self._records[(expected_tenant_id, delivery_id)] = updated
            return updated

    def _require(
        self,
        delivery_id: WhatsAppCustomerReplyDeliveryId,
        expected_tenant_id: str,
    ) -> WhatsAppCustomerReplyDeliveryRecord:
        record = self._records.get((expected_tenant_id, delivery_id))
        if record is None:
            raise ValueError("whatsapp delivery not found")
        return record


def derive_whatsapp_customer_reply_delivery_id(
    *,
    tenant_id: str,
    draft_id: str | uuid.UUID,
    governance_decision_id: str | uuid.UUID,
) -> WhatsAppCustomerReplyDeliveryId:
    tenant = _required_text("tenant_id", tenant_id)
    seed = "|".join(
        (
            tenant,
            _uuid_text("draft_id", draft_id),
            _uuid_text("governance_decision_id", governance_decision_id),
        )
    )
    return uuid.uuid5(_WHATSAPP_CUSTOMER_REPLY_DELIVERY_NAMESPACE, seed)


def _record_to_row(
    record: WhatsAppCustomerReplyDeliveryRecord,
) -> WhatsAppCustomerReplyDeliveryRow:
    return WhatsAppCustomerReplyDeliveryRow(
        delivery_id=record.delivery_id,
        tenant_id=record.tenant_id,
        draft_id=record.draft_id,
        proposal_id=record.proposal_id,
        governance_decision_id=record.governance_decision_id,
        phone_number_id=record.phone_number_id,
        recipient_phone_number=record.recipient_phone_number,
        draft_body_sha256=record.draft_body_sha256,
        status=record.status.value,
        provider_message_id=record.provider_message_id,
        provider_status_code=record.provider_status_code,
        error_code=record.error_code,
        created_at=record.created_at,
        updated_at=record.updated_at,
        sent_at=record.sent_at,
        metadata_json=dict(record.metadata),
    )


def _row_to_record(
    row: WhatsAppCustomerReplyDeliveryRow,
) -> WhatsAppCustomerReplyDeliveryRecord:
    return WhatsAppCustomerReplyDeliveryRecord(
        delivery_id=row.delivery_id,
        tenant_id=row.tenant_id,
        draft_id=row.draft_id,
        proposal_id=row.proposal_id,
        governance_decision_id=row.governance_decision_id,
        phone_number_id=row.phone_number_id,
        recipient_phone_number=row.recipient_phone_number,
        draft_body_sha256=row.draft_body_sha256,
        status=WhatsAppDeliveryStatus(row.status),
        provider_message_id=row.provider_message_id,
        provider_status_code=row.provider_status_code,
        error_code=row.error_code,
        created_at=row.created_at,
        updated_at=row.updated_at,
        sent_at=row.sent_at,
        metadata=dict(row.metadata_json),
    )


def _assert_expected_tenant(tenant_id: str, expected_tenant_id: str) -> None:
    if tenant_id != expected_tenant_id:
        raise ValueError("tenant_id does not match expected_tenant_id")


def _required_text(name: str, value: str) -> str:
    text = value.strip()
    if not text:
        raise ValueError(f"{name} must be non-empty")
    return text


def _uuid_text(name: str, value: str | uuid.UUID) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except ValueError as exc:
        raise ValueError(f"{name} must be a valid UUID") from exc


__all__ = [
    "InMemoryWhatsAppDeliveryRepository",
    "PostgresWhatsAppDeliveryRepository",
    "WhatsAppCustomerReplyDeliveryId",
    "WhatsAppCustomerReplyDeliveryRecord",
    "WhatsAppDeliveryRepository",
    "WhatsAppDeliveryStatus",
    "derive_whatsapp_customer_reply_delivery_id",
]
