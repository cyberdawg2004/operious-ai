"""Timeline event projection model."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Mapping, cast

from pydantic import BaseModel, ConfigDict, Field

from app.session.models.timeline_event import SessionTimelineEvent

_PRE_VERSIONED_SCHEMA_VERSION = "0"


@dataclass(frozen=True, slots=True)
class DiagnosticCompletedPayload:
    schema_version: str
    category: str | None
    confidence: float | None
    summary: str | None
    governance_decision_id: str | None
    retrieved_citations: list[dict[str, Any]]


@dataclass(frozen=True, slots=True)
class SessionOpenedPayload:
    schema_version: str
    scope: str | None
    external_handle: str | None
    tenant_id: str | None


@dataclass(frozen=True, slots=True)
class ResolutionProposalPayload:
    schema_version: str
    proposal_id: str | None
    governance_decision_id: str | None
    status: str | None
    evidence: list[dict[str, Any]]


@dataclass(frozen=True, slots=True)
class ActionExecutedPayload:
    schema_version: str
    tool_name: str | None
    idempotency_key: str | None
    status: str | None


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
        event_payload = cast(Mapping[str, Any], nested_payload)
        event_type = (
            _payload_str(payload, "event_type")
            or event.annotation
            or event.kind.value
        )
        timestamp = _payload_datetime(payload, "timestamp")
        return cls(
            timeline_event_id=str(event.event_id),
            session_id=str(event.session_id),
            dispatch_id=_payload_str(payload, "dispatch_id"),
            tenant_id=(
                _payload_str(payload, "tenant_id") or fallback_tenant_id
            ),
            event_type=event_type,
            timestamp=timestamp or event.occurred_at,
            payload=_project_payload(
                event_type=event_type,
                wrapper_payload=payload,
                event_payload=event_payload,
            ),
            created_at=event.recorded_at,
        )


def _payload_str(payload: Mapping[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if isinstance(value, str) and value:
        return value
    return None


def _project_payload(
    *,
    event_type: str,
    wrapper_payload: Mapping[str, Any],
    event_payload: Mapping[str, Any],
) -> dict[str, Any]:
    schema_version = (
        _payload_str(event_payload, "_schema_version")
        or _payload_str(wrapper_payload, "_schema_version")
        or _PRE_VERSIONED_SCHEMA_VERSION
    )
    if event_type == "diagnostic_analysis_completed":
        return asdict(
            DiagnosticCompletedPayload(
                schema_version=schema_version,
                category=(
                    _payload_str(event_payload, "category")
                    or _payload_str(event_payload, "diagnostic_category")
                ),
                confidence=_first_float(
                    _payload_float(event_payload, "confidence"),
                    _payload_float(
                        event_payload, "diagnostic_confidence"
                    ),
                ),
                summary=(
                    _payload_str(event_payload, "summary")
                    or _payload_str(event_payload, "diagnostic_summary")
                ),
                governance_decision_id=_payload_str(
                    event_payload, "governance_decision_id"
                ),
                retrieved_citations=_payload_list_of_dicts(
                    event_payload, "retrieved_citations"
                ),
            )
        )
    if event_type == "session_opened":
        return asdict(
            SessionOpenedPayload(
                schema_version=schema_version,
                scope=_payload_str(event_payload, "scope"),
                external_handle=_payload_str(
                    event_payload, "external_handle"
                ),
                tenant_id=_payload_str(event_payload, "tenant_id"),
            )
        )
    if event_type == "resolution_proposal_created":
        return asdict(
            ResolutionProposalPayload(
                schema_version=schema_version,
                proposal_id=_payload_str(event_payload, "proposal_id"),
                governance_decision_id=_payload_str(
                    event_payload, "governance_decision_id"
                ),
                status=_payload_str(event_payload, "status"),
                evidence=_payload_list_of_dicts(event_payload, "evidence"),
            )
        )
    if event_type == "action_executed":
        return asdict(
            ActionExecutedPayload(
                schema_version=schema_version,
                tool_name=_payload_str(event_payload, "tool_name"),
                idempotency_key=_payload_str(
                    event_payload, "idempotency_key"
                ),
                status=_payload_str(event_payload, "status"),
            )
        )
    return dict(event_payload)


def _payload_float(
    payload: Mapping[str, Any], key: str
) -> float | None:
    value = payload.get(key)
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str) and value:
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _payload_list_of_dicts(
    payload: Mapping[str, Any],
    key: str,
) -> list[dict[str, Any]]:
    value = payload.get(key)
    if not isinstance(value, (list, tuple)):
        return []
    raw_items = cast(list[object] | tuple[object, ...], value)
    items: list[dict[str, Any]] = []
    for item in raw_items:
        if isinstance(item, Mapping):
            items.append(dict(cast(Mapping[str, Any], item)))
    return items


def _first_float(*values: float | None) -> float | None:
    for value in values:
        if value is not None:
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


__all__ = [
    "ActionExecutedPayload",
    "DiagnosticCompletedPayload",
    "ResolutionProposalPayload",
    "SessionOpenedPayload",
    "TimelineEvent",
]
