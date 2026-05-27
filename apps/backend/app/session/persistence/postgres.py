"""Postgres implementation of :class:`SessionPersistenceProtocol`.

Behavioural parity with :class:`InMemorySessionPersistence` —
revision-monotonic session writes, append-only contiguous-sequence
event writes, tenant-scoped point/list reads.

Tenant scope is enforced inline (no shared
:class:`TenantScopedRepository` clamp) because the session ORM keeps
``tenant_id`` nullable (matching the in-memory record contract).
``WHERE tenant_id = $expected`` correctly excludes NULL rows from
scoped reads via SQL three-valued logic so tenantless sessions
remain invisible to a tenant-scoped caller.

Sub-record scope (events / correlations) inherits from the owning
session via a parent lookup, identical to the in-memory pattern.
The parent lookup is a single PK SELECT — index-only.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.repositories.base import BaseRepository
from app.repositories.pagination import fetch_scalar_page
from app.session.db.models import (
    SessionCorrelationRow,
    SessionEventRow,
    SessionRow,
)
from app.session.enums import (
    SessionContinuityMode,
    SessionCorrelationKind,
    SessionEventKind,
    SessionLifecyclePhase,
    SessionScope,
)
from app.session.exceptions import SessionPersistenceError
from app.session.identity import (
    SessionCorrelationId,
    SessionEventId,
    SessionId,
    SessionLineageId,
)
from app.session.persistence.models import (
    SessionCorrelationQuery,
    SessionEventQuery,
    SessionQuery,
    SessionRecordPage,
)
from app.session.persistence.records import (
    SessionCorrelationRecord,
    SessionEventRecord,
    SessionRecord,
)


class PostgresSessionPersistence(BaseRepository):
    """Postgres-backed session persistence.

    Constructor receives the request-scoped ``AsyncSession`` via
    :class:`BaseRepository`. Never commits, never rolls back —
    transaction ownership lives in the service layer.
    """

    # ─── Sessions: revision-monotonic overwrite ──────────────────────

    async def save_session(
        self, record: SessionRecord
    ) -> None:
        existing_stmt = select(SessionRow.revision).where(
            SessionRow.session_id == record.session_id
        )
        existing_revision = (
            await self.session.execute(existing_stmt)
        ).scalar_one_or_none()
        if existing_revision is not None and record.revision <= existing_revision:
            raise SessionPersistenceError(
                "non-monotonic revision: existing="
                f"{existing_revision}, incoming="
                f"{record.revision}"
            )
        try:
            # SAVEPOINT isolation — IntegrityError rolls back this
            # nested transaction only; the outer transaction (the
            # service layer's commit boundary, or a test fixture's
            # outer BEGIN) is untouched.
            async with self.session.begin_nested():
                if existing_revision is None:
                    self.session.add(_session_record_to_row(record))
                else:
                    existing_row = (
                        await self.session.execute(
                            select(SessionRow).where(
                                SessionRow.session_id == record.session_id
                            )
                        )
                    ).scalar_one()
                    _update_session_row(existing_row, record)
        except IntegrityError as exc:
            raise SessionPersistenceError(
                f"session {record.session_id} could not be persisted"
            ) from exc

    # ─── Events: append-only with contiguous sequence ────────────────

    async def save_event(
        self, record: SessionEventRecord
    ) -> None:
        # The substrate's contiguous-sequence contract requires the
        # incoming sequence to equal `head + 1` (or 0 for the first
        # event). Enforce at the application layer so the error
        # message matches the in-memory backend's wording — Postgres
        # would otherwise raise a generic UNIQUE violation.
        head_stmt = select(SessionRow.sequence_head).where(
            SessionRow.session_id == record.session_id
        )
        head = (
            await self.session.execute(head_stmt)
        ).scalar_one_or_none()
        bucket_count_stmt = select(func.count()).select_from(
            SessionEventRow
        ).where(
            SessionEventRow.session_id == record.session_id
        )
        existing_count = int(
            (await self.session.execute(bucket_count_stmt)).scalar_one()
        )
        if existing_count == 0 and record.sequence != 0:
            raise SessionPersistenceError(
                "first event of a session must have sequence 0"
            )
        if existing_count > 0:
            # Look up the actual highest persisted sequence (not the
            # session's sequence_head, which may lag the persisted
            # events when callers save events before save_session).
            max_stmt = select(func.max(SessionEventRow.sequence)).where(
                SessionEventRow.session_id == record.session_id
            )
            max_seq = (await self.session.execute(max_stmt)).scalar_one()
            if max_seq + 1 != record.sequence:
                raise SessionPersistenceError(
                    "non-monotonic event sequence: "
                    f"head={max_seq}, incoming={record.sequence}"
                )
        row = _event_record_to_row(record)
        try:
            # SAVEPOINT isolation — see save_session docstring.
            async with self.session.begin_nested():
                self.session.add(row)
        except IntegrityError as exc:
            reason = "duplicate event id"
            if record.idempotency_key is not None:
                reason = "duplicate event id or idempotency key"
            raise SessionPersistenceError(
                f"{reason}: {record.event_id}"
            ) from exc
        # Suppress the unused-binding warning when head is None — we
        # only need it to confirm the parent session row exists at
        # all paths that reach this point (FK enforces it too).
        _ = head

    # ─── Correlations: append-only by id ─────────────────────────────

    async def save_correlation(
        self, record: SessionCorrelationRecord
    ) -> None:
        row = _correlation_record_to_row(record)
        try:
            async with self.session.begin_nested():
                self.session.add(row)
        except IntegrityError as exc:
            raise SessionPersistenceError(
                f"duplicate correlation id: {record.correlation_id}"
            ) from exc

    # ─── Point reads ─────────────────────────────────────────────────

    async def get_session(
        self,
        session_id: SessionId,
        *,
        expected_tenant_id: str | None = None,
    ) -> SessionRecord | None:
        stmt = select(SessionRow).where(
            SessionRow.session_id == session_id
        )
        if expected_tenant_id is not None:
            stmt = stmt.where(SessionRow.tenant_id == expected_tenant_id)
        row = (
            await self.session.execute(stmt)
        ).scalar_one_or_none()
        return None if row is None else _session_row_to_record(row)

    async def get_event(
        self,
        event_id: SessionEventId,
        *,
        expected_tenant_id: str | None = None,
    ) -> SessionEventRecord | None:
        stmt = select(SessionEventRow).where(
            SessionEventRow.event_id == event_id
        )
        row = (
            await self.session.execute(stmt)
        ).scalar_one_or_none()
        if row is None:
            return None
        if expected_tenant_id is not None:
            parent_stmt = select(SessionRow.tenant_id).where(
                SessionRow.session_id == row.session_id
            )
            parent_tenant = (
                await self.session.execute(parent_stmt)
            ).scalar_one_or_none()
            if parent_tenant != expected_tenant_id:
                return None
        return _event_row_to_record(row)

    async def get_event_by_idempotency_key(
        self,
        *,
        session_id: SessionId,
        idempotency_key: str,
        expected_tenant_id: str | None = None,
    ) -> SessionEventRecord | None:
        stmt = select(SessionEventRow).where(
            SessionEventRow.session_id == session_id,
            SessionEventRow.idempotency_key == idempotency_key,
        )
        row = (
            await self.session.execute(stmt)
        ).scalar_one_or_none()
        if row is None:
            return None
        if expected_tenant_id is not None:
            parent_stmt = select(SessionRow.tenant_id).where(
                SessionRow.session_id == row.session_id
            )
            parent_tenant = (
                await self.session.execute(parent_stmt)
            ).scalar_one_or_none()
            if parent_tenant != expected_tenant_id:
                return None
        return _event_row_to_record(row)

    async def get_correlation(
        self,
        correlation_id: SessionCorrelationId,
        *,
        expected_tenant_id: str | None = None,
    ) -> SessionCorrelationRecord | None:
        stmt = select(SessionCorrelationRow).where(
            SessionCorrelationRow.correlation_id == correlation_id
        )
        row = (
            await self.session.execute(stmt)
        ).scalar_one_or_none()
        if row is None:
            return None
        if expected_tenant_id is not None:
            parent_stmt = select(SessionRow.tenant_id).where(
                SessionRow.session_id == row.session_id
            )
            parent_tenant = (
                await self.session.execute(parent_stmt)
            ).scalar_one_or_none()
            if parent_tenant != expected_tenant_id:
                return None
        return _correlation_row_to_record(row)

    # ─── List / query reads ──────────────────────────────────────────

    async def list_sessions(
        self,
        query: SessionQuery,
        *,
        expected_tenant_id: str | None = None,
    ) -> SessionRecordPage:
        stmt = select(SessionRow)
        if expected_tenant_id is not None:
            stmt = stmt.where(SessionRow.tenant_id == expected_tenant_id)
        if query.session_id is not None:
            stmt = stmt.where(SessionRow.session_id == query.session_id)
        if query.scope is not None:
            stmt = stmt.where(SessionRow.scope == query.scope.value)
        if query.tenant_id is not None:
            stmt = stmt.where(SessionRow.tenant_id == query.tenant_id)
        if query.principal_id is not None:
            stmt = stmt.where(
                SessionRow.principal_id == query.principal_id
            )
        if query.external_handle is not None:
            stmt = stmt.where(
                SessionRow.external_handle == query.external_handle
            )
        if query.lifecycle_phase is not None:
            stmt = stmt.where(
                SessionRow.lifecycle_phase == query.lifecycle_phase.value
            )
        # Newest sessions first so operational dashboards surface fresh
        # tickets on the first page. Session ID keeps ties deterministic.
        stmt = stmt.order_by(
            SessionRow.opened_at.desc(),
            SessionRow.session_id.desc(),
        )
        page = await fetch_scalar_page(
            self.session,
            stmt,
            limit=query.limit,
            offset=query.offset,
        )
        return SessionRecordPage(
            sessions=tuple(_session_row_to_record(r) for r in page.items),
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )

    async def list_events(
        self,
        query: SessionEventQuery,
        *,
        expected_tenant_id: str | None = None,
    ) -> SessionRecordPage:
        if expected_tenant_id is not None:
            parent_stmt = select(SessionRow.tenant_id).where(
                SessionRow.session_id == query.session_id
            )
            parent_tenant = (
                await self.session.execute(parent_stmt)
            ).scalar_one_or_none()
            if parent_tenant != expected_tenant_id:
                return SessionRecordPage(events=(), total=0)
        stmt = select(SessionEventRow).where(
            SessionEventRow.session_id == query.session_id
        )
        if query.event_id is not None:
            stmt = stmt.where(SessionEventRow.event_id == query.event_id)
        if query.kind is not None:
            stmt = stmt.where(SessionEventRow.kind == query.kind.value)
        if query.from_sequence is not None:
            stmt = stmt.where(
                SessionEventRow.sequence >= query.from_sequence
            )
        if query.to_sequence is not None:
            stmt = stmt.where(
                SessionEventRow.sequence <= query.to_sequence
            )
        if query.occurred_before_or_at is not None:
            stmt = stmt.where(
                SessionEventRow.occurred_at <= query.occurred_before_or_at
            )
        if query.occurred_after_or_at is not None:
            stmt = stmt.where(
                SessionEventRow.occurred_at >= query.occurred_after_or_at
            )
        stmt = stmt.order_by(SessionEventRow.sequence)
        page = await fetch_scalar_page(
            self.session,
            stmt,
            limit=query.limit,
            offset=query.offset,
        )
        return SessionRecordPage(
            events=tuple(_event_row_to_record(r) for r in page.items),
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )

    async def list_correlations(
        self,
        query: SessionCorrelationQuery,
        *,
        expected_tenant_id: str | None = None,
    ) -> SessionRecordPage:
        stmt = select(SessionCorrelationRow)
        if expected_tenant_id is not None:
            # Each correlation inherits scope from its owning session.
            # Composing a single statement with a subquery keeps the
            # tenant clamp inside the SQL (no per-row Python check).
            stmt = stmt.where(
                SessionCorrelationRow.session_id.in_(
                    select(SessionRow.session_id).where(
                        SessionRow.tenant_id == expected_tenant_id
                    )
                )
            )
        if query.session_id is not None:
            stmt = stmt.where(
                SessionCorrelationRow.session_id == query.session_id
            )
        if query.correlation_id is not None:
            stmt = stmt.where(
                SessionCorrelationRow.correlation_id == query.correlation_id
            )
        if query.kind is not None:
            stmt = stmt.where(
                SessionCorrelationRow.kind == query.kind.value
            )
        if query.external_id is not None:
            stmt = stmt.where(
                SessionCorrelationRow.external_id == query.external_id
            )
        # In-memory ordering: (session_id, recorded_at, correlation_id).
        stmt = stmt.order_by(
            SessionCorrelationRow.session_id,
            SessionCorrelationRow.recorded_at,
            SessionCorrelationRow.correlation_id,
        )
        page = await fetch_scalar_page(
            self.session,
            stmt,
            limit=query.limit,
            offset=query.offset,
        )
        return SessionRecordPage(
            correlations=tuple(
                _correlation_row_to_record(r) for r in page.items
            ),
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )


# ─── Record ↔ Row converters ────────────────────────────────────────────


def _session_record_to_row(record: SessionRecord) -> SessionRow:
    return SessionRow(
        session_id=record.session_id,
        scope=record.scope.value,
        external_handle=record.external_handle,
        tenant_id=record.tenant_id,
        principal_id=record.principal_id,
        opened_at=record.opened_at,
        lifecycle_phase=record.lifecycle_phase.value,
        lifecycle_recorded_at=record.lifecycle_recorded_at,
        lifecycle_reason=record.lifecycle_reason,
        lineage_id=record.lineage_id,
        root_session_id=record.root_session_id,
        parent_session_id=record.parent_session_id,
        ancestor_session_ids=[str(a) for a in record.ancestor_session_ids],
        lineage_depth=record.lineage_depth,
        sequence_head=record.sequence_head,
        revision=record.revision,
        context_environment=record.context_environment,
        context_labels=list(record.context_labels),
        context_attributes=dict(record.context_attributes),
        context_notes=record.context_notes,
        metadata_json=dict(record.metadata),
    )


def _update_session_row(
    row: SessionRow, record: SessionRecord
) -> None:
    """Apply a higher-revision record to an existing row in place.

    Sessions are revision-mutable on lifecycle / context / lineage
    fields (the substrate's contract). The PK and lineage roots
    never change once persisted; we still overwrite them
    defensively to keep behaviour identical to the in-memory
    repository which simply replaces the whole record.
    """
    row.scope = record.scope.value
    row.external_handle = record.external_handle
    row.tenant_id = record.tenant_id
    row.principal_id = record.principal_id
    row.opened_at = record.opened_at
    row.lifecycle_phase = record.lifecycle_phase.value
    row.lifecycle_recorded_at = record.lifecycle_recorded_at
    row.lifecycle_reason = record.lifecycle_reason
    row.lineage_id = record.lineage_id
    row.root_session_id = record.root_session_id
    row.parent_session_id = record.parent_session_id
    row.ancestor_session_ids = [
        str(a) for a in record.ancestor_session_ids
    ]
    row.lineage_depth = record.lineage_depth
    row.sequence_head = record.sequence_head
    row.revision = record.revision
    row.context_environment = record.context_environment
    row.context_labels = list(record.context_labels)
    row.context_attributes = dict(record.context_attributes)
    row.context_notes = record.context_notes
    row.metadata_json = dict(record.metadata)


def _event_record_to_row(
    record: SessionEventRecord,
) -> SessionEventRow:
    return SessionEventRow(
        event_id=record.event_id,
        session_id=record.session_id,
        sequence=record.sequence,
        kind=record.kind.value,
        continuity_mode=record.continuity_mode.value,
        occurred_at=record.occurred_at,
        recorded_at=record.recorded_at,
        payload=dict(record.payload),
        correlation_id=record.correlation_id,
        annotation=record.annotation,
        idempotency_key=record.idempotency_key,
        governance_decision_id=record.governance_decision_id,
        governance_chain_id=record.governance_chain_id,
        metadata_json=dict(record.metadata),
    )


def _correlation_record_to_row(
    record: SessionCorrelationRecord,
) -> SessionCorrelationRow:
    return SessionCorrelationRow(
        correlation_id=record.correlation_id,
        session_id=record.session_id,
        kind=record.kind.value,
        external_id=record.external_id,
        recorded_at=record.recorded_at,
        external_correlation_id=record.external_correlation_id,
        annotation=record.annotation,
        attributes=dict(record.attributes),
        metadata_json=dict(record.metadata),
    )


def _session_row_to_record(row: SessionRow) -> SessionRecord:
    return SessionRecord(
        session_id=SessionId(row.session_id),
        scope=SessionScope(row.scope),
        external_handle=row.external_handle,
        tenant_id=row.tenant_id,
        principal_id=row.principal_id,
        opened_at=row.opened_at,
        lifecycle_phase=SessionLifecyclePhase(row.lifecycle_phase),
        lifecycle_recorded_at=row.lifecycle_recorded_at,
        lifecycle_reason=row.lifecycle_reason,
        lineage_id=SessionLineageId(row.lineage_id),
        root_session_id=SessionId(row.root_session_id),
        parent_session_id=(
            SessionId(row.parent_session_id)
            if row.parent_session_id is not None
            else None
        ),
        ancestor_session_ids=tuple(
            SessionId(UUID(a))
            for a in _as_list_of_str(row.ancestor_session_ids)
        ),
        lineage_depth=row.lineage_depth,
        sequence_head=row.sequence_head,
        revision=row.revision,
        context_environment=row.context_environment,
        context_labels=tuple(_as_list_of_str(row.context_labels)),
        context_attributes=dict(_as_dict_of_any(row.context_attributes)),
        context_notes=row.context_notes,
        metadata=dict(_as_dict_of_any(row.metadata_json)),
    )


def _event_row_to_record(row: SessionEventRow) -> SessionEventRecord:
    return SessionEventRecord(
        event_id=SessionEventId(row.event_id),
        session_id=SessionId(row.session_id),
        sequence=row.sequence,
        kind=SessionEventKind(row.kind),
        continuity_mode=SessionContinuityMode(row.continuity_mode),
        occurred_at=row.occurred_at,
        recorded_at=row.recorded_at,
        payload=dict(_as_dict_of_any(row.payload)),
        correlation_id=(
            SessionCorrelationId(row.correlation_id)
            if row.correlation_id is not None
            else None
        ),
        annotation=row.annotation,
        idempotency_key=row.idempotency_key,
        governance_decision_id=row.governance_decision_id,
        governance_chain_id=row.governance_chain_id,
        metadata=dict(_as_dict_of_any(row.metadata_json)),
    )


def _correlation_row_to_record(
    row: SessionCorrelationRow,
) -> SessionCorrelationRecord:
    return SessionCorrelationRecord(
        correlation_id=SessionCorrelationId(row.correlation_id),
        session_id=SessionId(row.session_id),
        kind=SessionCorrelationKind(row.kind),
        external_id=row.external_id,
        recorded_at=row.recorded_at,
        external_correlation_id=row.external_correlation_id,
        annotation=row.annotation,
        attributes=dict(_as_dict_of_any(row.attributes)),
        metadata=dict(_as_dict_of_any(row.metadata_json)),
    )


# ─── JSONB → Python helpers ─────────────────────────────────────────────


def _as_list_of_str(value: Any) -> list[str]:
    """Coerce a JSONB value into ``list[str]``.

    SQLAlchemy returns JSONB columns as ``Any``; the substrate's
    record contracts demand concrete tuple / list types. The helper
    is defensive — a row whose JSONB blob does not contain a list
    is a substrate bug, but the helper returns an empty list to
    keep the read path total.
    """
    if isinstance(value, list):
        return [str(v) for v in value]  # pyright: ignore[reportUnknownVariableType]
    return []


def _as_dict_of_any(value: Any) -> dict[str, Any]:
    """Coerce a JSONB value into ``dict[str, Any]``."""
    if isinstance(value, dict):
        return {str(k): v for k, v in value.items()}  # pyright: ignore[reportUnknownVariableType]
    return {}


__all__ = ["PostgresSessionPersistence"]
