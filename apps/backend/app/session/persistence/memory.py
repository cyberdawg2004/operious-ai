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
        "_events_by_idempotency_key",
        "_events_by_session",
        "_correlations",
        "_lock",
    )

    def __init__(self) -> None:
        self._sessions: dict[SessionId, SessionRecord] = {}
        self._events: dict[
            SessionEventId, SessionEventRecord
        ] = {}
        self._events_by_idempotency_key: dict[
            tuple[SessionId, str], SessionEventRecord
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
    ) -> SessionRecord:
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
            return record

    # ─── Events: append-only ────────────────────────────────────────

    async def save_event(
        self, record: SessionEventRecord
    ) -> None:
        async with self._lock:
            if record.event_id in self._events:
                raise SessionPersistenceError(
                    f"duplicate event id: {record.event_id}"
                )
            if record.idempotency_key is not None:
                key = (record.session_id, record.idempotency_key)
                if key in self._events_by_idempotency_key:
                    raise SessionPersistenceError(
                        "duplicate event idempotency key: "
                        f"{record.idempotency_key}"
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
            if record.idempotency_key is not None:
                self._events_by_idempotency_key[
                    (record.session_id, record.idempotency_key)
                ] = record
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
        self,
        session_id: SessionId,
        *,
        expected_tenant_id: str | None = None,
    ) -> SessionRecord | None:
        record = self._sessions.get(session_id)
        if record is None:
            return None
        # 2.75-ε: tenant-scoped read. Row-level isolation —
        # a record belonging to another tenant is invisible
        # (returns None, indistinguishable from "not found").
        if (
            expected_tenant_id is not None
            and record.tenant_id != expected_tenant_id
        ):
            return None
        return record

    async def get_event(
        self,
        event_id: SessionEventId,
        *,
        expected_tenant_id: str | None = None,
    ) -> SessionEventRecord | None:
        record = self._events.get(event_id)
        if record is None:
            return None
        if expected_tenant_id is not None:
            session = self._sessions.get(record.session_id)
            if (
                session is None
                or session.tenant_id != expected_tenant_id
            ):
                return None
        return record

    async def get_event_by_idempotency_key(
        self,
        *,
        session_id: SessionId,
        idempotency_key: str,
        expected_tenant_id: str | None = None,
    ) -> SessionEventRecord | None:
        record = self._events_by_idempotency_key.get(
            (session_id, idempotency_key)
        )
        if record is None:
            return None
        if expected_tenant_id is not None:
            session = self._sessions.get(record.session_id)
            if (
                session is None
                or session.tenant_id != expected_tenant_id
            ):
                return None
        return record

    async def get_correlation(
        self,
        correlation_id: SessionCorrelationId,
        *,
        expected_tenant_id: str | None = None,
    ) -> SessionCorrelationRecord | None:
        record = self._correlations.get(correlation_id)
        if record is None:
            return None
        if expected_tenant_id is not None:
            session = self._sessions.get(record.session_id)
            if (
                session is None
                or session.tenant_id != expected_tenant_id
            ):
                return None
        return record

    async def list_sessions(
        self,
        query: SessionQuery,
        *,
        expected_tenant_id: str | None = None,
    ) -> SessionRecordPage:
        rows = list(self._sessions.values())
        # 2.75-ε (extended): system tenant scope is the strict
        # outer bound — it precedes any caller-supplied query
        # filter so cross-tenant rows cannot leak via list APIs.
        if expected_tenant_id is not None:
            rows = [r for r in rows if r.tenant_id == expected_tenant_id]
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
        rows.sort(
            key=lambda r: (r.opened_at, str(r.session_id)),
            reverse=True,
        )
        total = len(rows)
        if query.offset:
            rows = rows[query.offset :]
        if query.limit is not None:
            rows = rows[: query.limit]
        return SessionRecordPage(
            sessions=tuple(rows), total=total
        )

    async def list_events(
        self,
        query: SessionEventQuery,
        *,
        expected_tenant_id: str | None = None,
    ) -> SessionRecordPage:
        # 2.75-ε (extended): owning-session tenant gate.
        if expected_tenant_id is not None:
            owning = self._sessions.get(query.session_id)
            if (
                owning is None
                or owning.tenant_id != expected_tenant_id
            ):
                return SessionRecordPage(events=(), total=0)
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
        self,
        query: SessionCorrelationQuery,
        *,
        expected_tenant_id: str | None = None,
    ) -> SessionRecordPage:
        rows = list(self._correlations.values())
        # 2.75-ε (extended): each correlation inherits scope
        # from its owning session.
        if expected_tenant_id is not None:
            rows = [
                r
                for r in rows
                if (
                    (parent := self._sessions.get(r.session_id))
                    is not None
                    and parent.tenant_id == expected_tenant_id
                )
            ]
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
