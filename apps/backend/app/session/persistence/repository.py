"""Persistence protocol — append-only, deterministically ordered."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

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


@runtime_checkable
class SessionPersistenceProtocol(Protocol):
    """Storage-agnostic contract for session audit records.

    Implementations MUST:

    * Be append-only for `SessionEventRecord` (a re-save with the
      same event_id raises `SessionPersistenceError`).
    * Allow `save_session` to overwrite the apex record on every
      revision — sessions are mutable on lifecycle/context/lineage,
      but their TIMELINE remains append-only. The substrate
      enforces revision monotonicity at the runtime layer.
    * Return records in deterministic order (sequence-ordered for
      events, sorted-by-id for sessions/correlations).
    """

    async def save_session(self, record: SessionRecord) -> None: ...

    async def save_event(
        self, record: SessionEventRecord
    ) -> None: ...

    async def save_correlation(
        self, record: SessionCorrelationRecord
    ) -> None: ...

    async def get_session(
        self,
        session_id: SessionId,
        *,
        expected_tenant_id: str | None = None,
    ) -> SessionRecord | None:
        """Point read by session_id.

        Wedge 2.75-ε: when ``expected_tenant_id`` is supplied,
        records belonging to a DIFFERENT tenant MUST return
        ``None`` — the persisted row exists but is invisible from
        the requesting tenant's perspective (row-level isolation).
        ``None`` is also returned for the regular "not found" case,
        so callers cannot distinguish "absent" from "another
        tenant's row" — that distinction would leak existence
        across tenants.
        """
        ...

    async def get_event(
        self,
        event_id: SessionEventId,
        *,
        expected_tenant_id: str | None = None,
    ) -> SessionEventRecord | None:
        """Point read by event_id with optional tenant scoping.

        Tenant scope is resolved through the event's owning
        ``SessionRecord``: an event is visible from tenant T iff
        the session it belongs to is owned by T.
        """
        ...

    async def get_correlation(
        self,
        correlation_id: SessionCorrelationId,
        *,
        expected_tenant_id: str | None = None,
    ) -> SessionCorrelationRecord | None:
        """Point read by correlation_id with optional tenant scoping.

        Tenant scope resolved via the owning session, like
        :meth:`get_event`.
        """
        ...

    async def list_sessions(
        self, query: SessionQuery
    ) -> SessionRecordPage: ...

    async def list_events(
        self, query: SessionEventQuery
    ) -> SessionRecordPage: ...

    async def list_correlations(
        self, query: SessionCorrelationQuery
    ) -> SessionRecordPage: ...


__all__ = ["SessionPersistenceProtocol"]
