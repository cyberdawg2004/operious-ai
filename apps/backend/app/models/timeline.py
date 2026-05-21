"""Timeline event projection model."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field

from app.session.models.timeline_event import SessionTimelineEvent


class TimelineEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    timeline_event_id: str
    session_id: str
    dispatch_id: str | None = None
    tenant_id: str | None = None
    event_type: str
    timestamp: datetime
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime

    @classmethod
    def from_session_event(
        cls,
        event: SessionTimelineEvent,
        *,
        fallback_tenant_id: str | None = None,
    ) -> "TimelineEvent":
        payload = dict(event.payload)
        nested_payload = payload.get("payload")
        if not isinstance(nested_payload, Mapping):
            nested_payload = payload
        timestamp = _payload_datetime(payload, "timestamp")
        return cls(
            timeline_event_id=str(event.event_id),
            session_id=str(event.session_id),
            dispatch_id=_payload_str(payload, "dispatch_id"),
            tenant_id=(
                _payload_str(payload, "tenant_id") or fallback_tenant_id
            ),
            event_type=(
                _payload_str(payload, "event_type")
                or event.annotation
                or event.kind.value
            ),
            timestamp=timestamp or event.occurred_at,
            payload=dict(nested_payload),
            created_at=event.recorded_at,
        )


def _payload_str(payload: Mapping[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if isinstance(value, str) and value:
        return value
    return None


def _payload_datetime(
    payload: Mapping[str, Any], key: str
) -> datetime | None:
    value = payload.get(key)
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


__all__ = ["TimelineEvent"]
