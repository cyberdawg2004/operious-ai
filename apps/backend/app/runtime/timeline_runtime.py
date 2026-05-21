"""Append-only session timeline persistence runtime."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from app.models.timeline import TimelineEvent
from app.session.contracts.requests import AppendEventRequest
from app.session.contracts.results import AppendEventResult
from app.session.enums import (
    SessionContinuityMode,
    SessionEventKind,
)
from app.session.identity import as_session_id
from app.session.persistence import SessionPersistenceProtocol
from app.session.runtime import SessionRuntime
from app.session.serializers.canonical import canonicalize_payload


class TimelineRuntime:
    """Append diagnostic lifecycle events to the session timeline."""

    def __init__(
        self,
        *,
        persistence: SessionPersistenceProtocol,
    ) -> None:
        self._persistence = persistence

    async def append_event(
        self,
        *,
        session_id: str,
        dispatch_id: str,
        tenant_id: str,
        event_type: str,
        payload: Mapping[str, Any] | None = None,
        timestamp: datetime | None = None,
    ) -> TimelineEvent:
        event_timestamp = _coerce_timestamp(timestamp)
        sid = as_session_id(session_id)
        session = await self._persistence.get_session(
            sid, expected_tenant_id=tenant_id
        )
        if session is None:
            raise TimelineRuntimeError(
                "timeline append rejected for unknown tenant-scoped "
                f"session: {session_id}"
            )

        event_payload = canonicalize_payload(
            {
                "session_id": session_id,
                "dispatch_id": dispatch_id,
                "tenant_id": tenant_id,
                "event_type": event_type,
                "timestamp": event_timestamp.isoformat(),
                "payload": dict(payload or {}),
            }
        )
        envelope = await SessionRuntime(
            persistence=self._persistence,
        ).append_event(
            AppendEventRequest(
                session_id=sid,
                kind=SessionEventKind.OPERATIONAL_OBSERVATION,
                occurred_at=event_timestamp,
                continuity_mode=SessionContinuityMode.SYNCHRONOUS,
                payload=event_payload,
                annotation=event_type,
                external_correlation_id=dispatch_id,
                correlation_id=dispatch_id,
                request_id=dispatch_id,
                metadata={
                    "dispatch_id": dispatch_id,
                    "event_type": event_type,
                },
            )
        )
        if not envelope.is_ok or envelope.result is None:
            raise TimelineRuntimeError(
                "session runtime rejected timeline append"
            ) from envelope.error
        result = envelope.result
        if not isinstance(result, AppendEventResult) or result.event is None:
            raise TimelineRuntimeError(
                "session runtime returned an unexpected append result"
            )
        return TimelineEvent.from_session_event(
            result.event,
            fallback_tenant_id=tenant_id,
        )


class TimelineRuntimeError(RuntimeError):
    """Raised when a timeline event cannot be appended."""


def _coerce_timestamp(timestamp: datetime | None) -> datetime:
    if timestamp is None:
        return datetime.now(tz=timezone.utc)
    if timestamp.tzinfo is None:
        raise TimelineRuntimeError("timeline timestamp must be timezone-aware")
    return timestamp


__all__ = ["TimelineRuntime", "TimelineRuntimeError"]
