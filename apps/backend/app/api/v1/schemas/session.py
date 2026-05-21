"""Transport contracts for the v1 session read endpoints.

Mirrors :class:`SessionRecord`, :class:`SessionEventRecord`,
:class:`SessionCorrelationRecord` as frozen Pydantic schemas with
explicit ``from_record`` projections.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.timeline import TimelineEvent
from app.session.persistence import (
    SessionCorrelationRecord,
    SessionEventRecord,
    SessionRecord,
)
from app.session.models.timeline import SessionTimeline


class SessionResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_id: str
    scope: str
    external_handle: str
    tenant_id: str | None = None
    principal_id: str | None = None
    opened_at: str
    lifecycle_phase: str
    lifecycle_recorded_at: str
    lifecycle_reason: str | None = None
    lineage_id: str
    root_session_id: str
    parent_session_id: str | None = None
    ancestor_session_ids: list[str] = Field(default_factory=list)
    lineage_depth: int
    sequence_head: int
    revision: int
    context_environment: str | None = None
    context_labels: list[str] = Field(default_factory=list)
    context_attributes: dict[str, Any] = Field(default_factory=dict)
    context_notes: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_record(cls, record: SessionRecord) -> "SessionResponse":
        return cls(
            session_id=str(record.session_id),
            scope=record.scope.value,
            external_handle=record.external_handle,
            tenant_id=record.tenant_id,
            principal_id=record.principal_id,
            opened_at=record.opened_at.isoformat(),
            lifecycle_phase=record.lifecycle_phase.value,
            lifecycle_recorded_at=record.lifecycle_recorded_at.isoformat(),
            lifecycle_reason=record.lifecycle_reason,
            lineage_id=str(record.lineage_id),
            root_session_id=str(record.root_session_id),
            parent_session_id=(
                str(record.parent_session_id)
                if record.parent_session_id is not None
                else None
            ),
            ancestor_session_ids=[
                str(a) for a in record.ancestor_session_ids
            ],
            lineage_depth=record.lineage_depth,
            sequence_head=record.sequence_head,
            revision=record.revision,
            context_environment=record.context_environment,
            context_labels=list(record.context_labels),
            context_attributes=dict(record.context_attributes),
            context_notes=record.context_notes,
            metadata=dict(record.metadata),
        )


class SessionEventResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_id: str
    session_id: str
    sequence: int
    kind: str
    continuity_mode: str
    occurred_at: str
    recorded_at: str
    payload: dict[str, Any] = Field(default_factory=dict)
    correlation_id: str | None = None
    annotation: str | None = None
    governance_decision_id: str | None = None
    governance_chain_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_record(
        cls, record: SessionEventRecord
    ) -> "SessionEventResponse":
        return cls(
            event_id=str(record.event_id),
            session_id=str(record.session_id),
            sequence=record.sequence,
            kind=record.kind.value,
            continuity_mode=record.continuity_mode.value,
            occurred_at=record.occurred_at.isoformat(),
            recorded_at=record.recorded_at.isoformat(),
            payload=dict(record.payload),
            correlation_id=(
                str(record.correlation_id)
                if record.correlation_id is not None
                else None
            ),
            annotation=record.annotation,
            governance_decision_id=(
                str(record.governance_decision_id)
                if record.governance_decision_id is not None
                else None
            ),
            governance_chain_id=record.governance_chain_id,
            metadata=dict(record.metadata),
        )


class SessionCorrelationResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    correlation_id: str
    session_id: str
    kind: str
    external_id: str
    recorded_at: str
    external_correlation_id: str | None = None
    annotation: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_record(
        cls, record: SessionCorrelationRecord
    ) -> "SessionCorrelationResponse":
        return cls(
            correlation_id=str(record.correlation_id),
            session_id=str(record.session_id),
            kind=record.kind.value,
            external_id=record.external_id,
            recorded_at=record.recorded_at.isoformat(),
            external_correlation_id=record.external_correlation_id,
            annotation=record.annotation,
            attributes=dict(record.attributes),
            metadata=dict(record.metadata),
        )


class SessionsPage(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[SessionResponse] = Field(default_factory=list)
    total: int


class SessionEventsPage(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[SessionEventResponse] = Field(default_factory=list)
    total: int


class SessionCorrelationsPage(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[SessionCorrelationResponse] = Field(default_factory=list)
    total: int


class SessionTimelineResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    events: list[TimelineEvent] = Field(default_factory=list)
    total: int

    @classmethod
    def from_timeline(
        cls,
        timeline: SessionTimeline | None,
        *,
        fallback_tenant_id: str | None = None,
    ) -> "SessionTimelineResponse":
        events = (
            []
            if timeline is None
            else [
                TimelineEvent.from_session_event(
                    event,
                    fallback_tenant_id=fallback_tenant_id,
                )
                for event in timeline.events
            ]
        )
        return cls(events=events, total=len(events))


__all__ = [
    "SessionCorrelationResponse",
    "SessionCorrelationsPage",
    "SessionEventResponse",
    "SessionEventsPage",
    "SessionResponse",
    "SessionTimelineResponse",
    "SessionsPage",
]
