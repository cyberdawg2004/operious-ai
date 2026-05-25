"""Postgres implementation of :class:`BoundaryPersistenceProtocol`.

Behavioural parity with :class:`InMemoryBoundaryPersistence`:
egress remains write-once by id; ingress duplicate replay keys,
event ids, and ingress ids resolve to the original canonical record.
Reads remain tenant-scoped, and list ordering remains canonical
``(runtime_instance_id, sequence)`` ordering per table.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import delete, or_, select, tuple_
from sqlalchemy.exc import IntegrityError

from app.boundary.db.models import (
    BoundaryEgressRow,
    BoundaryIngressRow,
    WebhookNonceRecordRow,
)
from app.boundary.enums import (
    BoundaryDirection,
    BoundaryMessageType,
    BoundaryNormalizationStatus,
    BoundaryReplayDisposition,
    BoundarySourceType,
)
from app.boundary.exceptions import BoundaryPersistenceError, WebhookReplayError
from app.boundary.identity import (
    BoundaryEgressId,
    BoundaryEventId,
    BoundaryIngressId,
)
from app.boundary.persistence.models import (
    BoundaryEgressQuery,
    BoundaryIngressQuery,
    BoundaryRecordPage,
)
from app.boundary.persistence.records import (
    BoundaryEgressRecord,
    BoundaryIngressRecord,
    WebhookNonceRecord,
)
from app.repositories.base import BaseRepository
from app.repositories.pagination import fetch_scalar_page


class PostgresBoundaryPersistence(BaseRepository):
    """Postgres-backed boundary persistence."""

    # ─── Writes ──────────────────────────────────────────────────────

    async def save_ingress(
        self, record: BoundaryIngressRecord
    ) -> BoundaryIngressRecord:
        row = _ingress_record_to_row(record)
        try:
            # SAVEPOINT isolation — see governance repo for doctrine.
            async with self.session.begin_nested():
                self.session.add(row)
        except IntegrityError as exc:
            with self.session.no_autoflush:
                existing = await self._find_duplicate_ingress(record)
            if existing is not None:
                return existing
            raise BoundaryPersistenceError(
                f"duplicate ingress record: ingress_id={record.ingress_id}"
            ) from exc
        return record

    async def save_egress(self, record: BoundaryEgressRecord) -> None:
        row = _egress_record_to_row(record)
        try:
            async with self.session.begin_nested():
                self.session.add(row)
        except IntegrityError as exc:
            raise BoundaryPersistenceError(
                f"duplicate egress record: egress_id={record.egress_id}"
            ) from exc

    async def _find_duplicate_ingress(
        self, record: BoundaryIngressRecord
    ) -> BoundaryIngressRecord | None:
        predicates = [
            BoundaryIngressRow.ingress_id == record.ingress_id
        ]
        if record.replay_key is not None:
            predicates.append(
                BoundaryIngressRow.replay_key == record.replay_key
            )
        if record.event_id is not None:
            predicates.append(
                BoundaryIngressRow.event_id == record.event_id
            )
        stmt = (
            select(BoundaryIngressRow)
            .where(or_(*predicates))
            .order_by(
                BoundaryIngressRow.received_at,
                BoundaryIngressRow.runtime_instance_id,
                BoundaryIngressRow.sequence,
            )
            .limit(1)
        )
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        return None if row is None else _ingress_row_to_record(row)

    # ─── Point reads ─────────────────────────────────────────────────

    async def get_ingress(
        self,
        ingress_id: BoundaryIngressId,
        *,
        expected_tenant_id: str | None = None,
    ) -> BoundaryIngressRecord | None:
        stmt = select(BoundaryIngressRow).where(
            BoundaryIngressRow.ingress_id == ingress_id
        )
        if expected_tenant_id is not None:
            stmt = stmt.where(
                BoundaryIngressRow.tenant_id == expected_tenant_id
            )
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        return None if row is None else _ingress_row_to_record(row)

    async def get_egress(
        self,
        egress_id: BoundaryEgressId,
        *,
        expected_tenant_id: str | None = None,
    ) -> BoundaryEgressRecord | None:
        stmt = select(BoundaryEgressRow).where(
            BoundaryEgressRow.egress_id == egress_id
        )
        if expected_tenant_id is not None:
            stmt = stmt.where(
                BoundaryEgressRow.tenant_id == expected_tenant_id
            )
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        return None if row is None else _egress_row_to_record(row)

    # ─── List reads ──────────────────────────────────────────────────

    async def list_ingress(
        self,
        query: BoundaryIngressQuery,
        *,
        expected_tenant_id: str | None = None,
    ) -> BoundaryRecordPage:
        stmt = select(BoundaryIngressRow)
        if expected_tenant_id is not None:
            stmt = stmt.where(
                BoundaryIngressRow.tenant_id == expected_tenant_id
            )
        if query.ingress_id is not None:
            stmt = stmt.where(
                BoundaryIngressRow.ingress_id == query.ingress_id
            )
        if query.event_id is not None:
            stmt = stmt.where(
                BoundaryIngressRow.event_id == query.event_id
            )
        if query.replay_key is not None:
            stmt = stmt.where(
                BoundaryIngressRow.replay_key == query.replay_key
            )
        if query.source_type is not None:
            stmt = stmt.where(
                BoundaryIngressRow.source_type == query.source_type.value
            )
        if query.normalization_status is not None:
            stmt = stmt.where(
                BoundaryIngressRow.normalization_status
                == query.normalization_status.value
            )
        if query.replay_disposition is not None:
            stmt = stmt.where(
                BoundaryIngressRow.replay_disposition
                == query.replay_disposition.value
            )
        if query.correlation_id is not None:
            stmt = stmt.where(
                BoundaryIngressRow.correlation_id == query.correlation_id
            )
        if query.request_id is not None:
            stmt = stmt.where(
                BoundaryIngressRow.request_id == query.request_id
            )
        if query.tenant_id is not None:
            stmt = stmt.where(
                BoundaryIngressRow.tenant_id == query.tenant_id
            )
        stmt = stmt.order_by(
            BoundaryIngressRow.runtime_instance_id,
            BoundaryIngressRow.sequence,
        )
        page = await fetch_scalar_page(
            self.session,
            stmt,
            limit=query.limit,
            offset=query.offset,
        )
        return BoundaryRecordPage(
            ingress=tuple(_ingress_row_to_record(r) for r in page.items),
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )

    async def list_egress(
        self,
        query: BoundaryEgressQuery,
        *,
        expected_tenant_id: str | None = None,
    ) -> BoundaryRecordPage:
        stmt = select(BoundaryEgressRow)
        if expected_tenant_id is not None:
            stmt = stmt.where(
                BoundaryEgressRow.tenant_id == expected_tenant_id
            )
        if query.egress_id is not None:
            stmt = stmt.where(
                BoundaryEgressRow.egress_id == query.egress_id
            )
        if query.source_type is not None:
            stmt = stmt.where(
                BoundaryEgressRow.source_type == query.source_type.value
            )
        if query.correlation_id is not None:
            stmt = stmt.where(
                BoundaryEgressRow.correlation_id == query.correlation_id
            )
        if query.request_id is not None:
            stmt = stmt.where(
                BoundaryEgressRow.request_id == query.request_id
            )
        if query.tenant_id is not None:
            stmt = stmt.where(
                BoundaryEgressRow.tenant_id == query.tenant_id
            )
        stmt = stmt.order_by(
            BoundaryEgressRow.runtime_instance_id,
            BoundaryEgressRow.sequence,
        )
        page = await fetch_scalar_page(
            self.session,
            stmt,
            limit=query.limit,
            offset=query.offset,
        )
        return BoundaryRecordPage(
            egress=tuple(_egress_row_to_record(r) for r in page.items),
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )

    # ─── Webhook replay protection ───────────────────────────────────

    async def record_webhook_nonce(
        self,
        record: WebhookNonceRecord,
    ) -> None:
        await self.session.execute(
            delete(WebhookNonceRecordRow).where(
                WebhookNonceRecordRow.tenant_id == record.tenant_id,
                WebhookNonceRecordRow.channel_type == record.channel_type,
                WebhookNonceRecordRow.nonce == record.nonce,
                WebhookNonceRecordRow.expires_at <= record.received_at,
            )
        )
        row = WebhookNonceRecordRow(
            tenant_id=record.tenant_id,
            channel_type=record.channel_type,
            nonce=record.nonce,
            received_at=record.received_at,
            expires_at=record.expires_at,
        )
        try:
            async with self.session.begin_nested():
                self.session.add(row)
        except IntegrityError as exc:
            raise WebhookReplayError(
                "webhook nonce has already been accepted"
            ) from exc

    async def webhook_nonce_exists(
        self,
        *,
        tenant_id: str,
        channel_type: str,
        nonce: str,
        now: datetime,
    ) -> bool:
        stmt = (
            select(WebhookNonceRecordRow.nonce)
            .where(
                WebhookNonceRecordRow.tenant_id == tenant_id,
                WebhookNonceRecordRow.channel_type
                == channel_type.strip().lower(),
                WebhookNonceRecordRow.nonce == nonce,
                WebhookNonceRecordRow.expires_at > now,
            )
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none() is not None

    async def delete_expired_webhook_nonces(
        self,
        *,
        now: datetime,
        limit: int = 1000,
    ) -> int:
        if limit < 1:
            raise ValueError("limit must be positive")
        expired = (
            select(
                WebhookNonceRecordRow.tenant_id.label("tenant_id"),
                WebhookNonceRecordRow.channel_type.label("channel_type"),
                WebhookNonceRecordRow.nonce.label("nonce"),
            )
            .where(WebhookNonceRecordRow.expires_at <= now)
            .order_by(WebhookNonceRecordRow.expires_at)
            .limit(limit)
            .cte("expired_webhook_nonces")
        )
        stmt = (
            delete(WebhookNonceRecordRow)
            .where(
                tuple_(
                    WebhookNonceRecordRow.tenant_id,
                    WebhookNonceRecordRow.channel_type,
                    WebhookNonceRecordRow.nonce,
                ).in_(
                    select(
                        expired.c.tenant_id,
                        expired.c.channel_type,
                        expired.c.nonce,
                    )
                )
            )
            .returning(WebhookNonceRecordRow.nonce)
        )
        result = await self.session.execute(stmt)
        return sum(1 for _ in result.scalars())


# ─── Record ↔ Row converters ────────────────────────────────────────────


def _ingress_record_to_row(
    record: BoundaryIngressRecord,
) -> BoundaryIngressRow:
    return BoundaryIngressRow(
        ingress_id=record.ingress_id,
        direction=record.direction.value,
        runtime_instance_id=record.runtime_instance_id,
        sequence=record.sequence,
        source_type=record.source_type.value,
        source_id=record.source_id,
        tenant_id=record.tenant_id,
        adapter_name=record.adapter_name,
        normalization_status=record.normalization_status.value,
        message_type=record.message_type.value,
        replay_disposition=record.replay_disposition.value,
        replay_key=record.replay_key,
        event_id=record.event_id,
        original_event_id=record.original_event_id,
        external_message_id=record.external_message_id,
        external_conversation_id=record.external_conversation_id,
        external_emitted_at=record.external_emitted_at,
        received_at=record.received_at,
        started_at=record.started_at,
        ended_at=record.ended_at,
        latency_ms=record.latency_ms,
        correlation_id=record.correlation_id,
        request_id=record.request_id,
        canonical_payload=dict(record.canonical_payload),
        error=record.error,
        metadata_json=dict(record.metadata),
    )


def _ingress_row_to_record(
    row: BoundaryIngressRow,
) -> BoundaryIngressRecord:
    return BoundaryIngressRecord(
        ingress_id=BoundaryIngressId(row.ingress_id),
        direction=BoundaryDirection(row.direction),
        runtime_instance_id=row.runtime_instance_id,
        sequence=row.sequence,
        source_type=BoundarySourceType(row.source_type),
        source_id=row.source_id,
        tenant_id=row.tenant_id,
        adapter_name=row.adapter_name,
        normalization_status=BoundaryNormalizationStatus(
            row.normalization_status
        ),
        message_type=BoundaryMessageType(row.message_type),
        replay_disposition=BoundaryReplayDisposition(
            row.replay_disposition
        ),
        replay_key=row.replay_key,
        event_id=(
            BoundaryEventId(row.event_id)
            if row.event_id is not None
            else None
        ),
        original_event_id=(
            BoundaryEventId(row.original_event_id)
            if row.original_event_id is not None
            else None
        ),
        external_message_id=row.external_message_id,
        external_conversation_id=row.external_conversation_id,
        external_emitted_at=row.external_emitted_at,
        received_at=row.received_at,
        started_at=row.started_at,
        ended_at=row.ended_at,
        latency_ms=row.latency_ms,
        correlation_id=row.correlation_id,
        request_id=row.request_id,
        canonical_payload=_as_dict(row.canonical_payload),
        error=row.error,
        metadata=_as_dict(row.metadata_json),
    )


def _egress_record_to_row(
    record: BoundaryEgressRecord,
) -> BoundaryEgressRow:
    return BoundaryEgressRow(
        egress_id=record.egress_id,
        direction=record.direction.value,
        runtime_instance_id=record.runtime_instance_id,
        sequence=record.sequence,
        source_type=record.source_type.value,
        source_id=record.source_id,
        tenant_id=record.tenant_id,
        adapter_name=record.adapter_name,
        payload_body=record.payload_body,
        payload_content_type=record.payload_content_type,
        payload_target_uri=record.payload_target_uri,
        payload_method=record.payload_method,
        payload_headers=dict(record.payload_headers),
        translated_at=record.translated_at,
        started_at=record.started_at,
        ended_at=record.ended_at,
        latency_ms=record.latency_ms,
        correlation_id=record.correlation_id,
        request_id=record.request_id,
        error=record.error,
        metadata_json=dict(record.metadata),
    )


def _egress_row_to_record(
    row: BoundaryEgressRow,
) -> BoundaryEgressRecord:
    return BoundaryEgressRecord(
        egress_id=BoundaryEgressId(row.egress_id),
        direction=BoundaryDirection(row.direction),
        runtime_instance_id=row.runtime_instance_id,
        sequence=row.sequence,
        source_type=BoundarySourceType(row.source_type),
        source_id=row.source_id,
        tenant_id=row.tenant_id,
        adapter_name=row.adapter_name,
        payload_body=row.payload_body,
        payload_content_type=row.payload_content_type,
        payload_target_uri=row.payload_target_uri,
        payload_method=row.payload_method,
        payload_headers=_as_dict_of_str(row.payload_headers),
        translated_at=row.translated_at,
        started_at=row.started_at,
        ended_at=row.ended_at,
        latency_ms=row.latency_ms,
        correlation_id=row.correlation_id,
        request_id=row.request_id,
        error=row.error,
        metadata=_as_dict(row.metadata_json),
    )


# ─── JSONB coercion ─────────────────────────────────────────────────────


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return {str(k): v for k, v in value.items()}  # pyright: ignore[reportUnknownVariableType]
    return {}


def _as_dict_of_str(value: Any) -> dict[str, str]:
    if isinstance(value, dict):
        return {str(k): str(v) for k, v in value.items()}  # pyright: ignore[reportUnknownVariableType]
    return {}


__all__ = ["PostgresBoundaryPersistence"]
