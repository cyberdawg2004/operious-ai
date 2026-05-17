"""In-memory persistence backend (test + dev).

Append-only on events; revision-monotonic on sessions; sorted-by-id
on correlations. Asyncio-locked for concurrent runtime calls.
"""

from __future__ import annotations

import asyncio

from app.session.exceptions import SessionPersistenceError
from app.session.identity import (
    SessionCorrelationId,
    SessionEventId,
    SessionId,
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


class InMemorySessionPersistence:
    """Test/dev-grade in-memory implementation of the persistence protocol."""

    __slots__ = (
        "_sessions",
        "_events",
        "_events_by_session",
        "_correlations",
        "_lock",
    )

    def __init__(self) -> None:
        self._sessions: dict[SessionId, SessionRecord] = {}
        self._events: dict[
            SessionEventId, SessionEventRecord
        ] = {}
        self._events_by_session: dict[
            SessionId, list[SessionEventRecord]
        ] = {}
        self._correlations: dict[
            SessionCorrelationId, SessionCorrelationRecord
        ] = {}
        self._lock = asyncio.Lock()

    # ─── Sessions: revision-monotonic overwrite ─────────────────────

    async def save_session(
        self, record: SessionRecord
    ) -> None:
        async with self._lock:
            existing = self._sessions.get(record.session_id)
            if existing is not None and (
                record.revision <= existing.revision
            ):
                raise SessionPersistenceError(
                    f"non-monotonic revision: existing="
                    f"{existing.revision}, incoming="
                    f"{record.revision}"
                )
            self._sessions[record.session_id] = record

    # ─── Events: append-only ────────────────────────────────────────

    async def save_event(
        self, record: SessionEventRecord
    ) -> None:
        async with self._lock:
            if record.event_id in self._events:
                raise SessionPersistenceError(
                    f"duplicate event id: {record.event_id}"
                )
            bucket = self._events_by_session.setdefault(
                record.session_id, []
            )
            if bucket and bucket[-1].sequence + 1 != record.sequence:
                raise SessionPersistenceError(
                    "non-monotonic event sequence: "
                    f"head={bucket[-1].sequence}, "
                    f"incoming={record.sequence}"
                )
            if not bucket and record.sequence != 0:
                raise SessionPersistenceError(
                    "first event of a session must have sequence 0"
                )
            self._events[record.event_id] = record
            bucket.append(record)

    # ─── Correlations: append-only by id ────────────────────────────

    async def save_correlation(
        self, record: SessionCorrelationRecord
    ) -> None:
        async with self._lock:
            if record.correlation_id in self._correlations:
                raise SessionPersistenceError(
                    "duplicate correlation id: "
                    f"{record.correlation_id}"
                )
            self._correlations[record.correlation_id] = record

    # ─── Reads ──────────────────────────────────────────────────────

    async def get_session(
        self, session_id: SessionId
    ) -> SessionRecord | None:
        return self._sessions.get(session_id)

    async def get_event(
        self, event_id: SessionEventId
    ) -> SessionEventRecord | None:
        return self._events.get(event_id)

    async def get_correlation(
        self, correlation_id: SessionCorrelationId
    ) -> SessionCorrelationRecord | None:
        return self._correlations.get(correlation_id)

    async def list_sessions(
        self, query: SessionQuery
    ) -> SessionRecordPage:
        rows = list(self._sessions.values())
        if query.session_id is not None:
            rows = [
                r for r in rows if r.session_id == query.session_id
            ]
        if query.scope is not None:
            rows = [r for r in rows if r.scope == query.scope]
        if query.tenant_id is not None:
            rows = [r for r in rows if r.tenant_id == query.tenant_id]
        if query.principal_id is not None:
            rows = [
                r
                for r in rows
                if r.principal_id == query.principal_id
            ]
        if query.external_handle is not None:
            rows = [
                r
                for r in rows
                if r.external_handle == query.external_handle
            ]
        if query.lifecycle_phase is not None:
            rows = [
                r
                for r in rows
                if r.lifecycle_phase == query.lifecycle_phase
            ]
        rows.sort(key=lambda r: str(r.session_id))
        total = len(rows)
        if query.offset:
            rows = rows[query.offset :]
        if query.limit is not None:
            rows = rows[: query.limit]
        return SessionRecordPage(
            sessions=tuple(rows), total=total
        )

    async def list_events(
        self, query: SessionEventQuery
    ) -> SessionRecordPage:
        rows = list(self._events_by_session.get(query.session_id, []))
        if query.event_id is not None:
            rows = [r for r in rows if r.event_id == query.event_id]
        if query.kind is not None:
            rows = [r for r in rows if r.kind == query.kind]
        if query.from_sequence is not None:
            rows = [
                r for r in rows if r.sequence >= query.from_sequence
            ]
        if query.to_sequence is not None:
            rows = [
                r for r in rows if r.sequence <= query.to_sequence
            ]
        if query.occurred_before_or_at is not None:
            rows = [
                r
                for r in rows
                if r.occurred_at <= query.occurred_before_or_at
            ]
        if query.occurred_after_or_at is not None:
            rows = [
                r
                for r in rows
                if r.occurred_at >= query.occurred_after_or_at
            ]
        rows.sort(key=lambda r: r.sequence)
        total = len(rows)
        if query.offset:
            rows = rows[query.offset :]
        if query.limit is not None:
            rows = rows[: query.limit]
        return SessionRecordPage(events=tuple(rows), total=total)

    async def list_correlations(
        self, query: SessionCorrelationQuery
    ) -> SessionRecordPage:
        rows = list(self._correlations.values())
        if query.session_id is not None:
            rows = [
                r for r in rows if r.session_id == query.session_id
            ]
        if query.correlation_id is not None:
            rows = [
                r
                for r in rows
                if r.correlation_id == query.correlation_id
            ]
        if query.kind is not None:
            rows = [r for r in rows if r.kind == query.kind]
        if query.external_id is not None:
            rows = [
                r for r in rows if r.external_id == query.external_id
            ]
        rows.sort(
            key=lambda r: (
                str(r.session_id),
                r.recorded_at.isoformat(),
                str(r.correlation_id),
            )
        )
        total = len(rows)
        if query.offset:
            rows = rows[query.offset :]
        if query.limit is not None:
            rows = rows[: query.limit]
        return SessionRecordPage(
            correlations=tuple(rows), total=total
        )


__all__ = ["InMemorySessionPersistence"]
