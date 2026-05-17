"""Runtime ↔ persistence projection helpers."""

from __future__ import annotations

from app.session.models.context import SessionContext
from app.session.models.correlation import SessionCorrelation
from app.session.models.identity import SessionIdentity
from app.session.models.lifecycle import SessionLifecycle
from app.session.models.lineage import SessionLineage
from app.session.models.session import OperationalSession
from app.session.models.timeline_event import (
    SessionTimelineEvent,
)
from app.session.persistence.records import (
    SessionCorrelationRecord,
    SessionEventRecord,
    SessionRecord,
)


def session_to_record(
    session: OperationalSession,
) -> SessionRecord:
    return SessionRecord(
        session_id=session.identity.session_id,
        scope=session.identity.scope,
        external_handle=session.identity.external_handle,
        tenant_id=session.identity.tenant_id,
        principal_id=session.identity.principal_id,
        opened_at=session.opened_at,
        lifecycle_phase=session.lifecycle.phase,
        lifecycle_recorded_at=session.lifecycle.recorded_at,
        lifecycle_reason=session.lifecycle.reason,
        lineage_id=session.lineage.lineage_id,
        root_session_id=session.lineage.root_session_id,
        parent_session_id=session.lineage.parent_session_id,
        ancestor_session_ids=tuple(
            session.lineage.ancestor_session_ids
        ),
        lineage_depth=session.lineage.depth,
        sequence_head=session.sequence_head,
        revision=session.revision,
        context_environment=(
            session.context.environment
            if session.context is not None
            else None
        ),
        context_labels=(
            tuple(session.context.labels)
            if session.context is not None
            else ()
        ),
        context_attributes=(
            dict(session.context.attributes)
            if session.context is not None
            else {}
        ),
        context_notes=(
            session.context.notes
            if session.context is not None
            else None
        ),
    )


def record_to_session(
    record: SessionRecord,
) -> OperationalSession:
    identity = SessionIdentity(
        session_id=record.session_id,
        scope=record.scope,
        external_handle=record.external_handle,
        tenant_id=record.tenant_id,
        principal_id=record.principal_id,
    )
    lifecycle = SessionLifecycle(
        phase=record.lifecycle_phase,
        recorded_at=record.lifecycle_recorded_at,
        reason=record.lifecycle_reason,
    )
    lineage = SessionLineage(
        lineage_id=record.lineage_id,
        session_id=record.session_id,
        root_session_id=record.root_session_id,
        parent_session_id=record.parent_session_id,
        ancestor_session_ids=tuple(record.ancestor_session_ids),
        depth=record.lineage_depth,
    )
    context = (
        SessionContext(
            environment=record.context_environment,
            labels=tuple(record.context_labels),
            attributes=dict(record.context_attributes),
            notes=record.context_notes,
        )
        if (
            record.context_environment is not None
            or record.context_labels
            or record.context_attributes
            or record.context_notes is not None
        )
        else None
    )
    return OperationalSession(
        identity=identity,
        opened_at=record.opened_at,
        lifecycle=lifecycle,
        lineage=lineage,
        context=context,
        sequence_head=record.sequence_head,
        revision=record.revision,
    )


def event_to_record(
    event: SessionTimelineEvent,
) -> SessionEventRecord:
    return SessionEventRecord(
        event_id=event.event_id,
        session_id=event.session_id,
        sequence=event.sequence,
        kind=event.kind,
        continuity_mode=event.continuity_mode,
        occurred_at=event.occurred_at,
        recorded_at=event.recorded_at,
        payload=dict(event.payload),
        correlation_id=event.correlation_id,
        annotation=event.annotation,
    )


def event_record_to_model(
    record: SessionEventRecord,
) -> SessionTimelineEvent:
    return SessionTimelineEvent(
        event_id=record.event_id,
        session_id=record.session_id,
        sequence=record.sequence,
        kind=record.kind,
        continuity_mode=record.continuity_mode,
        occurred_at=record.occurred_at,
        recorded_at=record.recorded_at,
        payload=dict(record.payload),
        correlation_id=record.correlation_id,
        annotation=record.annotation,
    )


def correlation_record_to_model(
    record: SessionCorrelationRecord,
) -> SessionCorrelation:
    return SessionCorrelation(
        correlation_id=record.correlation_id,
        session_id=record.session_id,
        kind=record.kind,
        external_id=record.external_id,
        recorded_at=record.recorded_at,
        external_correlation_id=record.external_correlation_id,
        annotation=record.annotation,
        attributes=dict(record.attributes),
    )


def correlation_to_record(
    correlation: SessionCorrelation,
) -> SessionCorrelationRecord:
    return SessionCorrelationRecord(
        correlation_id=correlation.correlation_id,
        session_id=correlation.session_id,
        kind=correlation.kind,
        external_id=correlation.external_id,
        recorded_at=correlation.recorded_at,
        external_correlation_id=correlation.external_correlation_id,
        annotation=correlation.annotation,
        attributes=dict(correlation.attributes),
    )


__all__ = [
    "correlation_record_to_model",
    "correlation_to_record",
    "event_record_to_model",
    "event_to_record",
    "record_to_session",
    "session_to_record",
]
