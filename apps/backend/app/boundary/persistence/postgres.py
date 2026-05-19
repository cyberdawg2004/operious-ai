"""Postgres implementation of :class:`BoundaryPersistenceProtocol`.

Behavioural parity with :class:`InMemoryBoundaryPersistence` —
write-once on each direction, tenant-scoped point + list reads,
canonical ``(runtime_instance_id, sequence)`` ordering on each
table independently.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.boundary.db.models import (
    BoundaryEgressRow,
    BoundaryIngressRow,
)
from app.boundary.enums import (
    BoundaryDirection,
    BoundaryMessageType,
    BoundaryNormalizationStatus,
    BoundaryReplayDisposition,
    BoundarySourceType,
)
from app.boundary.exceptions import BoundaryPersistenceError
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
)
from app.repositories.base import BaseRepository


class PostgresBoundaryPersistence(BaseRepository):
    """Postgres-backed boundary persistence."""

    # ─── Writes ──────────────────────────────────────────────────────

    async def save_ingress(self, record: BoundaryIngressRecord) -> None:
        self.session.add(_ingress_record_to_row(record))
        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            raise BoundaryPersistenceError(
                f"duplicate ingress record: ingress_id={record.ingress_id}"
            ) from exc

    async def save_egress(self, record: BoundaryEgressRecord) -> None:
        self.session.add(_egress_record_to_row(record))
        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            raise BoundaryPersistenceError(
                f"duplicate egress record: egress_id={record.egress_id}"
            ) from exc

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
        all_rows = list(
            (await self.session.execute(stmt)).scalars().all()
        )
        total = len(all_rows)
        sliced = all_rows[query.offset :]
        if query.limit is not None:
            sliced = sliced[: query.limit]
        return BoundaryRecordPage(
            ingress=tuple(_ingress_row_to_record(r) for r in sliced),
            total=total,
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
        all_rows = list(
            (await self.session.execute(stmt)).scalars().all()
        )
        total = len(all_rows)
        sliced = all_rows[query.offset :]
        if query.limit is not None:
            sliced = sliced[: query.limit]
        return BoundaryRecordPage(
            egress=tuple(_egress_row_to_record(r) for r in sliced),
            total=total,
        )


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
