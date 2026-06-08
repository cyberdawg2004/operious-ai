"""Email customer-reply delivery ledger."""

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

from app.boundary.db.models import EmailCustomerReplyDeliveryRow
from app.repositories.base import BaseRepository

EmailCustomerReplyDeliveryId = uuid.UUID

_EMAIL_CUSTOMER_REPLY_DELIVERY_NAMESPACE = uuid.UUID(
    "2b7b4f5a-0001-4b01-9001-000000000004"
)


class EmailDeliveryStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class EmailCustomerReplyDeliveryRecord:
    delivery_id: EmailCustomerReplyDeliveryId
    tenant_id: str
    draft_id: uuid.UUID
    proposal_id: uuid.UUID
    governance_decision_id: uuid.UUID
    source_email_address: str
    recipient_email_address: str
    draft_body_sha256: str
    subject: str
    in_reply_to_message_id: str | None
    references_header: str | None
    status: EmailDeliveryStatus
    provider_message_id: str | None
    provider_status_code: int | None
    error_code: str | None
    created_at: datetime
    updated_at: datetime
    sent_at: datetime | None
    metadata: Mapping[str, Any]


@runtime_checkable
class EmailDeliveryRepository(Protocol):
    async def reserve_delivery(
        self,
        record: EmailCustomerReplyDeliveryRecord,
        *,
        expected_tenant_id: str,
    ) -> tuple[EmailCustomerReplyDeliveryRecord, bool]: ...

    async def get_delivery(
        self,
        delivery_id: EmailCustomerReplyDeliveryId,
        *,
        expected_tenant_id: str,
    ) -> EmailCustomerReplyDeliveryRecord | None: ...

    async def mark_sent(
        self,
        delivery_id: EmailCustomerReplyDeliveryId,
        *,
        expected_tenant_id: str,
        provider_message_id: str,
        provider_status_code: int,
        sent_at: datetime,
    ) -> EmailCustomerReplyDeliveryRecord: ...

    async def mark_failed(
        self,
        delivery_id: EmailCustomerReplyDeliveryId,
        *,
        expected_tenant_id: str,
        error_code: str,
        failed_at: datetime,
        provider_status_code: int | None = None,
    ) -> EmailCustomerReplyDeliveryRecord: ...


class PostgresEmailDeliveryRepository(BaseRepository):
    """Postgres-backed email delivery ledger."""

    async def reserve_delivery(
        self,
        record: EmailCustomerReplyDeliveryRecord,
        *,
        expected_tenant_id: str,
    ) -> tuple[EmailCustomerReplyDeliveryRecord, bool]:
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
        delivery_id: EmailCustomerReplyDeliveryId,
        *,
        expected_tenant_id: str,
    ) -> EmailCustomerReplyDeliveryRecord | None:
        row = await self._delivery_row(
            delivery_id,
            expected_tenant_id=expected_tenant_id,
        )
        return None if row is None else _row_to_record(row)

    async def mark_sent(
        self,
        delivery_id: EmailCustomerReplyDeliveryId,
        *,
        expected_tenant_id: str,
        provider_message_id: str,
        provider_status_code: int,
        sent_at: datetime,
    ) -> EmailCustomerReplyDeliveryRecord:
        return await self._update_delivery(
            delivery_id,
            expected_tenant_id=expected_tenant_id,
            values={
                "status": EmailDeliveryStatus.SENT.value,
                "provider_message_id": provider_message_id,
                "provider_status_code": provider_status_code,
                "sent_at": sent_at,
                "updated_at": sent_at,
                "error_code": None,
            },
        )

    async def mark_failed(
        self,
        delivery_id: EmailCustomerReplyDeliveryId,
        *,
        expected_tenant_id: str,
        error_code: str,
        failed_at: datetime,
        provider_status_code: int | None = None,
    ) -> EmailCustomerReplyDeliveryRecord:
        return await self._update_delivery(
            delivery_id,
            expected_tenant_id=expected_tenant_id,
            values={
                "status": EmailDeliveryStatus.FAILED.value,
                "provider_status_code": provider_status_code,
                "updated_at": failed_at,
                "error_code": error_code,
            },
        )

    async def _update_delivery(
        self,
        delivery_id: EmailCustomerReplyDeliveryId,
        *,
        expected_tenant_id: str,
        values: Mapping[str, Any],
    ) -> EmailCustomerReplyDeliveryRecord:
        stmt = (
            update(EmailCustomerReplyDeliveryRow)
            .where(
                EmailCustomerReplyDeliveryRow.delivery_id == delivery_id,
                EmailCustomerReplyDeliveryRow.tenant_id == expected_tenant_id,
            )
            .values(**dict(values))
        )
        result = cast(CursorResult[Any], await self.session.execute(stmt))
        if result.rowcount != 1:
            raise ValueError("email delivery not found")
        row = await self._delivery_row(
            delivery_id,
            expected_tenant_id=expected_tenant_id,
        )
        if row is None:
            raise ValueError("email delivery not found")
        return _row_to_record(row)

    async def _delivery_row(
        self,
        delivery_id: EmailCustomerReplyDeliveryId,
        *,
        expected_tenant_id: str,
    ) -> EmailCustomerReplyDeliveryRow | None:
        stmt = select(EmailCustomerReplyDeliveryRow).where(
            EmailCustomerReplyDeliveryRow.delivery_id == delivery_id,
            EmailCustomerReplyDeliveryRow.tenant_id == expected_tenant_id,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()


class InMemoryEmailDeliveryRepository:
    """In-memory email delivery ledger for unit tests."""

    def __init__(self) -> None:
        self._records: dict[tuple[str, uuid.UUID], EmailCustomerReplyDeliveryRecord]
        self._records = {}
        self._lock = asyncio.Lock()

    async def reserve_delivery(
        self,
        record: EmailCustomerReplyDeliveryRecord,
        *,
        expected_tenant_id: str,
    ) -> tuple[EmailCustomerReplyDeliveryRecord, bool]:
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
        delivery_id: EmailCustomerReplyDeliveryId,
        *,
        expected_tenant_id: str,
    ) -> EmailCustomerReplyDeliveryRecord | None:
        return self._records.get((expected_tenant_id, delivery_id))

    async def mark_sent(
        self,
        delivery_id: EmailCustomerReplyDeliveryId,
        *,
        expected_tenant_id: str,
        provider_message_id: str,
        provider_status_code: int,
        sent_at: datetime,
    ) -> EmailCustomerReplyDeliveryRecord:
        async with self._lock:
            record = self._require(delivery_id, expected_tenant_id)
            updated = replace(
                record,
                status=EmailDeliveryStatus.SENT,
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
        delivery_id: EmailCustomerReplyDeliveryId,
        *,
        expected_tenant_id: str,
        error_code: str,
        failed_at: datetime,
        provider_status_code: int | None = None,
    ) -> EmailCustomerReplyDeliveryRecord:
        async with self._lock:
            record = self._require(delivery_id, expected_tenant_id)
            updated = replace(
                record,
                status=EmailDeliveryStatus.FAILED,
                provider_status_code=provider_status_code,
                error_code=error_code,
                updated_at=failed_at,
            )
            self._records[(expected_tenant_id, delivery_id)] = updated
            return updated

    def _require(
        self,
        delivery_id: EmailCustomerReplyDeliveryId,
        expected_tenant_id: str,
    ) -> EmailCustomerReplyDeliveryRecord:
        record = self._records.get((expected_tenant_id, delivery_id))
        if record is None:
            raise ValueError("email delivery not found")
        return record


def derive_email_customer_reply_delivery_id(
    *,
    tenant_id: str,
    draft_id: str | uuid.UUID,
    governance_decision_id: str | uuid.UUID,
) -> EmailCustomerReplyDeliveryId:
    tenant = _required_text("tenant_id", tenant_id)
    seed = "|".join(
        (
            tenant,
            _uuid_text("draft_id", draft_id),
            _uuid_text("governance_decision_id", governance_decision_id),
        )
    )
    return uuid.uuid5(_EMAIL_CUSTOMER_REPLY_DELIVERY_NAMESPACE, seed)


def _record_to_row(
    record: EmailCustomerReplyDeliveryRecord,
) -> EmailCustomerReplyDeliveryRow:
    return EmailCustomerReplyDeliveryRow(
        delivery_id=record.delivery_id,
        tenant_id=record.tenant_id,
        draft_id=record.draft_id,
        proposal_id=record.proposal_id,
        governance_decision_id=record.governance_decision_id,
        source_email_address=record.source_email_address,
        recipient_email_address=record.recipient_email_address,
        draft_body_sha256=record.draft_body_sha256,
        subject=record.subject,
        in_reply_to_message_id=record.in_reply_to_message_id,
        references_header=record.references_header,
        status=record.status.value,
        provider_message_id=record.provider_message_id,
        provider_status_code=record.provider_status_code,
        error_code=record.error_code,
        created_at=record.created_at,
        updated_at=record.updated_at,
        sent_at=record.sent_at,
        metadata_json=dict(record.metadata),
    )


def _row_to_record(row: EmailCustomerReplyDeliveryRow) -> EmailCustomerReplyDeliveryRecord:
    return EmailCustomerReplyDeliveryRecord(
        delivery_id=row.delivery_id,
        tenant_id=row.tenant_id,
        draft_id=row.draft_id,
        proposal_id=row.proposal_id,
        governance_decision_id=row.governance_decision_id,
        source_email_address=row.source_email_address,
        recipient_email_address=row.recipient_email_address,
        draft_body_sha256=row.draft_body_sha256,
        subject=row.subject,
        in_reply_to_message_id=row.in_reply_to_message_id,
        references_header=row.references_header,
        status=EmailDeliveryStatus(row.status),
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
    "EmailCustomerReplyDeliveryId",
    "EmailCustomerReplyDeliveryRecord",
    "EmailDeliveryRepository",
    "EmailDeliveryStatus",
    "InMemoryEmailDeliveryRepository",
    "PostgresEmailDeliveryRepository",
    "derive_email_customer_reply_delivery_id",
]
