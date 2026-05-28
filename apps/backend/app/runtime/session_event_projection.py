"""Phase 2-B/2-C session timeline -> operational event projection bridge.

This adapter is intentionally outside ``SessionRuntime`` and
``OperationalEventRuntime``. It composes the two substrate authorities
without giving either one ownership of the other's semantics.

Phase 2-B introduced the bridge for the session-open genesis event.
Phase 2-C widens that bridge to the complete session timeline
classification ontology while keeping the bridge outside live runtime
mutation paths.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

from app.events import (
    EventCausality,
    EventChronology,
    EventId,
    OperationalEvent,
    OperationalEventRuntime,
    OperationalSubstrate,
)
from app.governance.capability.acts import OperationalAct
from app.governance.enums import Decision
from app.session.enums import SessionEventKind
from app.session.identity import (
    SessionId,
    derive_event_id as derive_session_event_id,
)
from app.session.models.session import OperationalSession
from app.session.models.timeline_event import SessionTimelineEvent
from app.session.persistence.models import SessionEventQuery
from app.session.persistence.repository import SessionPersistenceProtocol
from app.session.persistence.serializers import (
    event_record_to_model,
    record_to_session,
)
from app.session.serializers.canonical import canonicalize_payload


class SessionEventProjectionError(RuntimeError):
    """Raised when a session timeline event cannot be projected."""


@dataclass(frozen=True, slots=True)
class SessionOperationalEventProjection:
    """One projected source timeline event and its canonical event."""

    source_event: SessionTimelineEvent
    operational_event: OperationalEvent


class SessionOperationalEventProjector:
    """Projects session chronology into the canonical event fabric.

    This is a controlled adoption bridge, not a live orchestration path:
    it reads through session persistence and writes through
    ``OperationalEventRuntime``. It never mutates session chronology and
    never calls transport.
    """

    def __init__(
        self,
        *,
        session_persistence: SessionPersistenceProtocol,
        event_runtime: OperationalEventRuntime,
    ) -> None:
        self._session_persistence = session_persistence
        self._event_runtime = event_runtime

    async def project_session_opened_event(
        self,
        session_id: SessionId,
        *,
        expected_tenant_id: str | None = None,
    ) -> SessionOperationalEventProjection:
        """Project the genesis session event into event fabric."""

        session_record = await self._session_persistence.get_session(
            session_id,
            expected_tenant_id=expected_tenant_id,
        )
        if session_record is None:
            raise SessionEventProjectionError(
                f"unknown session for event projection: {session_id}"
            )
        page = await self._session_persistence.list_events(
            SessionEventQuery(
                session_id=session_id,
                kind=SessionEventKind.SESSION_OPENED,
                from_sequence=0,
                to_sequence=0,
                limit=1,
            ),
            expected_tenant_id=expected_tenant_id,
        )
        if page.total != 1 or not page.events:
            raise SessionEventProjectionError(
                "session-open projection requires exactly one "
                f"sequence-0 opened event; found {page.total}"
            )

        session = record_to_session(session_record)
        source_event = event_record_to_model(page.events[0])
        projected = project_session_timeline_event(
            session=session,
            event=source_event,
        )
        append = await self._event_runtime.append_event(
            projected,
            expected_tenant_id=session.identity.tenant_id,
        )
        return SessionOperationalEventProjection(
            source_event=source_event,
            operational_event=append.event,
        )

    async def project_session_events(
        self,
        session_id: SessionId,
        *,
        expected_tenant_id: str | None = None,
    ) -> tuple[SessionOperationalEventProjection, ...]:
        """Project every persisted event in one session timeline."""

        session_record = await self._session_persistence.get_session(
            session_id,
            expected_tenant_id=expected_tenant_id,
        )
        if session_record is None:
            raise SessionEventProjectionError(
                f"unknown session for event projection: {session_id}"
            )
        page = await self._session_persistence.list_events(
            SessionEventQuery(session_id=session_id),
            expected_tenant_id=expected_tenant_id,
        )
        session = record_to_session(session_record)
        projections: list[SessionOperationalEventProjection] = []
        for source_record in page.events:
            source_event = event_record_to_model(source_record)
            projected = project_session_timeline_event(
                session=session,
                event=source_event,
            )
            append = await self._event_runtime.append_event(
                projected,
                expected_tenant_id=session.identity.tenant_id,
            )
            projections.append(
                SessionOperationalEventProjection(
                    source_event=source_event,
                    operational_event=append.event,
                )
            )
        return tuple(projections)


def project_session_timeline_event(
    *,
    session: OperationalSession,
    event: SessionTimelineEvent,
) -> OperationalEvent:
    """Convert one supported session timeline event to an OperationalEvent."""

    if event.session_id != session.identity.session_id:
        raise SessionEventProjectionError(
            "session timeline event belongs to a different session"
        )
    if event.kind is SessionEventKind.SESSION_OPENED and event.sequence != 0:
        raise SessionEventProjectionError(
            "session-open projection requires sequence 0"
        )

    event_id = _project_session_event_id(event)
    decision_id = _optional_str(event.payload.get("governance_decision_id"))
    return OperationalEvent(
        event_id=event_id,
        operational_act=SESSION_EVENT_KIND_TO_OPERATIONAL_ACT[event.kind],
        substrate=OperationalSubstrate.SESSION,
        causality=_project_session_event_causality(event),
        chronology=EventChronology(
            runtime_instance_id=_chronology_lane_id(event.session_id),
            sequence=event.sequence,
            occurred_at=event.occurred_at,
        ),
        tenant_id=session.identity.tenant_id,
        principal_id=session.identity.principal_id,
        tenant_authority_source=_optional_str(
            event.payload.get("tenant_authority_source")
        ),
        governance_decision=(
            Decision.ALLOW if decision_id is not None else None
        ),
        governance_decision_id=decision_id,
        metadata=_projection_metadata(session=session, event=event),
    )


SESSION_EVENT_KIND_TO_OPERATIONAL_ACT: Mapping[
    SessionEventKind,
    OperationalAct,
] = {
    SessionEventKind.SESSION_OPENED: OperationalAct.SESSION_OPEN,
    SessionEventKind.CONTEXT_ATTACHED: OperationalAct.SESSION_ATTACH_CONTEXT,
    SessionEventKind.CORRELATION_RECORDED: (
        OperationalAct.SESSION_RECORD_CORRELATION
    ),
    SessionEventKind.LINEAGE_LINKED: OperationalAct.SESSION_LINK_LINEAGE,
    SessionEventKind.LIFECYCLE_RECLASSIFIED: (
        OperationalAct.SESSION_RECLASSIFY_LIFECYCLE
    ),
    SessionEventKind.DORMANCY_RECORDED: (
        OperationalAct.SESSION_RECORD_DORMANCY
    ),
    SessionEventKind.RESUMPTION_RECORDED: (
        OperationalAct.SESSION_RECORD_RESUMPTION
    ),
    SessionEventKind.TERMINATION_RECORDED: (
        OperationalAct.SESSION_RECORD_TERMINATION
    ),
    SessionEventKind.ARCHIVAL_RECORDED: (
        OperationalAct.SESSION_RECORD_ARCHIVAL
    ),
    SessionEventKind.OPERATIONAL_OBSERVATION: (
        OperationalAct.SESSION_OBSERVE_OPERATION
    ),
    SessionEventKind.CUSTOMER_MESSAGE: (
        OperationalAct.SESSION_RECORD_CUSTOMER_MESSAGE
    ),
    SessionEventKind.ASSISTANT_RESPONSE: (
        OperationalAct.SESSION_RECORD_ASSISTANT_RESPONSE
    ),
}


def _project_session_event_id(event: SessionTimelineEvent) -> EventId:
    # Use the existing session timeline event id as the canonical
    # fabric id for this projection. A second derived id for the same
    # chronology fact would create avoidable identity bifurcation.
    return EventId(str(event.event_id))


def _project_session_event_causality(
    event: SessionTimelineEvent,
) -> EventCausality:
    root_event_id = EventId(
        str(derive_session_event_id(session_id=event.session_id, sequence=0))
    )
    if event.sequence == 0:
        return EventCausality(
            root_event_id=root_event_id,
            parent_event_id=None,
            depth=0,
        )
    return EventCausality(
        root_event_id=root_event_id,
        parent_event_id=EventId(
            str(
                derive_session_event_id(
                    session_id=event.session_id,
                    sequence=event.sequence - 1,
                )
            )
        ),
        depth=event.sequence,
    )


def _chronology_lane_id(session_id: SessionId) -> uuid.UUID:
    # For projected session chronology, the stable session id is the
    # replayable chronology lane. The process runtime id is intentionally
    # not used because it is not persisted on historical timeline events.
    return uuid.UUID(str(session_id))


def _projection_metadata(
    *,
    session: OperationalSession,
    event: SessionTimelineEvent,
) -> Mapping[str, Any]:
    timeline_payload = dict(event.payload)
    cognition_audit_id = _cognition_audit_id_from_payload(timeline_payload)
    return canonicalize_payload(
        {
            "projection_source": "session_timeline",
            "source_event_id": str(event.event_id),
            "source_event_kind": event.kind.value,
            "source_session_id": str(event.session_id),
            "source_sequence": event.sequence,
            "session_scope": session.identity.scope.value,
            "session_external_handle": session.identity.external_handle,
            "session_lineage_id": str(session.lineage.lineage_id),
            "session_root_session_id": str(session.lineage.root_session_id),
            "session_parent_session_id": (
                str(session.lineage.parent_session_id)
                if session.lineage.parent_session_id is not None
                else None
            ),
            "session_lineage_depth": session.lineage.depth,
            "timeline_continuity_mode": event.continuity_mode.value,
            "timeline_recorded_at": event.recorded_at.isoformat(),
            "timeline_correlation_id": (
                str(event.correlation_id)
                if event.correlation_id is not None
                else None
            ),
            "timeline_annotation": event.annotation,
            "timeline_idempotency_key": event.idempotency_key,
            "timeline_payload": timeline_payload,
            "cognition_audit_id": cognition_audit_id,
            "cognition_audit_record_id": cognition_audit_id,
        }
    )


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None


def _cognition_audit_id_from_payload(payload: Mapping[str, Any]) -> str | None:
    nested = payload.get("payload")
    if isinstance(nested, Mapping):
        nested_payload = cast(Mapping[str, Any], nested)
        nested_value: Any | None = nested_payload.get(
            "cognition_audit_id"
        ) or nested_payload.get(
            "cognition_audit_record_id"
        )
        if nested_value is not None:
            return str(nested_value)
    value: Any | None = payload.get("cognition_audit_id") or payload.get(
        "cognition_audit_record_id"
    )
    return str(value) if value is not None else None


__all__ = [
    "SessionEventProjectionError",
    "SessionOperationalEventProjection",
    "SessionOperationalEventProjector",
    "SESSION_EVENT_KIND_TO_OPERATIONAL_ACT",
    "project_session_timeline_event",
]
