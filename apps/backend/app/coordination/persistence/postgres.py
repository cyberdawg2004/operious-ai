"""Postgres implementation of :class:`CoordinationPersistenceProtocol`.

Behavioural parity with :class:`InMemoryCoordinationPersistence` —
write-once envelope records, tenant-scoped point/list reads,
deterministic ``(runtime_instance_id, sequence)`` ordering.

Tenant clamp is inlined (no shared
:class:`TenantScopedRepository` clamp) because the coordination
record permits ``tenant_id is None`` (system / broadcast envelopes).
``WHERE tenant_id = $expected`` correctly excludes ``NULL`` via
SQL three-valued logic, matching the governance / session pattern.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.coordination.db.models import CoordinationEnvelopeRow
from app.coordination.exceptions import CoordinationPersistenceError
from app.coordination.persistence.models import (
    CoordinationQuery,
    RecordPage,
)
from app.coordination.persistence.records import CoordinationRecord
from app.repositories.base import BaseRepository


class PostgresCoordinationPersistence(BaseRepository):
    """Postgres-backed coordination persistence."""

    # ─── Writes ──────────────────────────────────────────────────────

    async def record_envelope(self, record: CoordinationRecord) -> None:
        row = _record_to_row(record)
        try:
            # SAVEPOINT isolation — IntegrityError rolls back the
            # nested transaction only, leaving the outer transaction
            # (the service layer's commit boundary) untouched.
            async with self.session.begin_nested():
                self.session.add(row)
        except IntegrityError as exc:
            raise CoordinationPersistenceError(
                f"coordination_id {record.coordination_id!r} already "
                "recorded; records are write-once"
            ) from exc

    # ─── Reads ───────────────────────────────────────────────────────

    async def get_envelope(
        self,
        coordination_id: str,
        *,
        expected_tenant_id: str | None = None,
    ) -> CoordinationRecord | None:
        stmt = select(CoordinationEnvelopeRow).where(
            CoordinationEnvelopeRow.coordination_id
            == UUID(coordination_id)
        )
        if expected_tenant_id is not None:
            stmt = stmt.where(
                CoordinationEnvelopeRow.tenant_id == expected_tenant_id
            )
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        return None if row is None else _row_to_record(row)

    async def query_envelopes(
        self,
        query: CoordinationQuery,
        *,
        expected_tenant_id: str | None = None,
    ) -> RecordPage[CoordinationRecord]:
        stmt = select(CoordinationEnvelopeRow)
        if expected_tenant_id is not None:
            stmt = stmt.where(
                CoordinationEnvelopeRow.tenant_id == expected_tenant_id
            )
        stmt = _apply_filters(stmt, query)
        # Canonical global ordering per Protocol contract.
        stmt = stmt.order_by(
            CoordinationEnvelopeRow.runtime_instance_id,
            CoordinationEnvelopeRow.sequence,
        )
        # Mirror the in-memory count semantics: materialise full
        # result set, then slice. Postgres-native COUNT(*) over the
        # same predicate would be cheaper; we keep parity for now
        # (per-PR-B1 doctrine: behaviour parity > optimisation).
        all_rows = list(
            (await self.session.execute(stmt)).scalars().all()
        )
        total = len(all_rows)
        sliced = all_rows[query.offset : query.offset + query.limit]
        return RecordPage(
            items=tuple(_row_to_record(r) for r in sliced),
            total=total,
            offset=query.offset,
        )


# ─── Filter composer ────────────────────────────────────────────────────


def _apply_filters(stmt, query: CoordinationQuery):  # type: ignore[no-untyped-def]
    """Mirror ``InMemoryCoordinationPersistence._matches`` field-by-field."""
    if query.coordination_id is not None:
        stmt = stmt.where(
            CoordinationEnvelopeRow.coordination_id
            == UUID(query.coordination_id)
        )
    if query.message_id is not None:
        stmt = stmt.where(
            CoordinationEnvelopeRow.message_id == UUID(query.message_id)
        )
    if query.sender_id is not None:
        stmt = stmt.where(
            CoordinationEnvelopeRow.sender_id == query.sender_id
        )
    if query.recipient_id is not None:
        stmt = stmt.where(
            CoordinationEnvelopeRow.recipient_id == query.recipient_id
        )
    if query.correlation_id is not None:
        stmt = stmt.where(
            CoordinationEnvelopeRow.correlation_id == query.correlation_id
        )
    if query.parent_coordination_id is not None:
        stmt = stmt.where(
            CoordinationEnvelopeRow.parent_coordination_id
            == UUID(query.parent_coordination_id)
        )
    if query.request_id is not None:
        stmt = stmt.where(
            CoordinationEnvelopeRow.request_id == query.request_id
        )
    if query.tenant_id is not None:
        stmt = stmt.where(
            CoordinationEnvelopeRow.tenant_id == query.tenant_id
        )
    if query.runtime_instance_id is not None:
        stmt = stmt.where(
            CoordinationEnvelopeRow.runtime_instance_id
            == UUID(query.runtime_instance_id)
        )
    if query.direction is not None:
        stmt = stmt.where(
            CoordinationEnvelopeRow.direction == query.direction
        )
    if query.message_type is not None:
        stmt = stmt.where(
            CoordinationEnvelopeRow.message_type == query.message_type
        )
    if query.status is not None:
        stmt = stmt.where(
            CoordinationEnvelopeRow.status == query.status
        )
    return stmt


# ─── Record ↔ Row converters ────────────────────────────────────────────


def _record_to_row(record: CoordinationRecord) -> CoordinationEnvelopeRow:
    from datetime import datetime

    return CoordinationEnvelopeRow(
        coordination_id=UUID(record.coordination_id),
        message_id=UUID(record.message_id),
        sender_id=record.sender_id,
        recipient_id=record.recipient_id,
        recipient_kind=record.recipient_kind,
        direction=record.direction,
        message_type=record.message_type,
        priority=record.priority,
        status=record.status,
        sequence=record.sequence,
        runtime_instance_id=UUID(record.runtime_instance_id),
        correlation_id=record.correlation_id,
        parent_coordination_id=(
            UUID(record.parent_coordination_id)
            if record.parent_coordination_id is not None
            else None
        ),
        parent_message_id=(
            UUID(record.parent_message_id)
            if record.parent_message_id is not None
            else None
        ),
        in_reply_to=(
            UUID(record.in_reply_to)
            if record.in_reply_to is not None
            else None
        ),
        request_id=record.request_id,
        tenant_id=record.tenant_id,
        tenant_authority_source=record.tenant_authority_source,
        governance_decision_id=(
            UUID(record.governance_decision_id)
            if record.governance_decision_id is not None
            else None
        ),
        governance_chain_id=record.governance_chain_id,
        payload_content_type=record.payload_content_type,
        payload_schema_version=record.payload_schema_version,
        payload_body=dict(record.payload_body),
        created_at=datetime.fromisoformat(record.created_at),
        dispatched_at=datetime.fromisoformat(record.dispatched_at),
        recipient_metadata=dict(record.recipient_metadata),
        payload_metadata=dict(record.payload_metadata),
        message_metadata=dict(record.message_metadata),
        envelope_metadata=dict(record.envelope_metadata),
    )


def _row_to_record(row: CoordinationEnvelopeRow) -> CoordinationRecord:
    return CoordinationRecord(
        coordination_id=str(row.coordination_id),
        message_id=str(row.message_id),
        sender_id=row.sender_id,
        recipient_id=row.recipient_id,
        recipient_kind=row.recipient_kind,
        direction=row.direction,
        message_type=row.message_type,
        priority=row.priority,
        status=row.status,
        sequence=row.sequence,
        runtime_instance_id=str(row.runtime_instance_id),
        correlation_id=row.correlation_id,
        parent_coordination_id=(
            str(row.parent_coordination_id)
            if row.parent_coordination_id is not None
            else None
        ),
        parent_message_id=(
            str(row.parent_message_id)
            if row.parent_message_id is not None
            else None
        ),
        in_reply_to=(
            str(row.in_reply_to)
            if row.in_reply_to is not None
            else None
        ),
        request_id=row.request_id,
        tenant_id=row.tenant_id,
        tenant_authority_source=row.tenant_authority_source,
        governance_decision_id=(
            str(row.governance_decision_id)
            if row.governance_decision_id is not None
            else None
        ),
        governance_chain_id=row.governance_chain_id,
        payload_content_type=row.payload_content_type,
        payload_schema_version=row.payload_schema_version,
        payload_body=_as_dict(row.payload_body),
        created_at=row.created_at.isoformat(),
        dispatched_at=row.dispatched_at.isoformat(),
        recipient_metadata=_as_dict(row.recipient_metadata),
        payload_metadata=_as_dict(row.payload_metadata),
        message_metadata=_as_dict(row.message_metadata),
        envelope_metadata=_as_dict(row.envelope_metadata),
    )


def _as_dict(value: Any) -> dict[str, Any]:
    """Coerce a JSONB column into ``dict[str, Any]``."""
    if isinstance(value, dict):
        return {str(k): v for k, v in value.items()}  # pyright: ignore[reportUnknownVariableType]
    return {}


__all__ = ["PostgresCoordinationPersistence"]
