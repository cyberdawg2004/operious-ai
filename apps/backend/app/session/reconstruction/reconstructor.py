"""`SessionReconstructor` — pure historical rebuild.

`reconstruct(...)` is the substrate's authoritative replay
function: given a `ReconstructSessionRequest` and a persistence
backend, it returns a deterministically-built continuity snapshot
of the session at the requested instant.

Discipline:

* Reconstruction NEVER invokes sibling substrates.
* Reconstruction NEVER mutates persistence.
* Reconstruction NEVER produces "what to do next" output.
* Same persisted records + same request → byte-identical
  reconstruction result. This is asserted in the test-suite's
  replay-equivalence invariant.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.session.contracts.requests import (
    ReconstructSessionRequest,
)
from app.session.enums import (
    SessionContinuityMode,
    SessionReconstructionStatus,
)
from app.session.exceptions import (
    SessionReconstructionError,
)
from app.session.identity import (
    SessionId,
    derive_event_id,
)
from app.session.models.correlation import SessionCorrelation
from app.session.models.lineage import SessionLineage
from app.session.models.session import OperationalSession
from app.session.models.timeline import SessionTimeline
from app.session.models.timeline_event import (
    SessionTimelineEvent,
)
from app.session.persistence.models import (
    SessionCorrelationQuery,
    SessionEventQuery,
)
from app.session.persistence.repository import (
    SessionPersistenceProtocol,
)
from app.session.persistence.serializers import (
    correlation_record_to_model,
    event_record_to_model,
    record_to_session,
)


@dataclass(frozen=True, slots=True)
class _ReconstructionPayload:
    """Internal aggregate for `reconstruct(...)`."""

    status: SessionReconstructionStatus
    session: OperationalSession | None
    timeline: SessionTimeline | None
    lineage: SessionLineage | None
    correlations: tuple[SessionCorrelation, ...]
    error: str | None = None


class SessionReconstructor:
    """Pure reconstruction pipeline.

    The reconstructor is stateless. It is constructed once and
    reused by the runtime for every reconstruction call.
    """

    __slots__ = ()

    async def reconstruct(
        self,
        *,
        request: ReconstructSessionRequest,
        persistence: SessionPersistenceProtocol,
    ) -> _ReconstructionPayload:
        """Run the reconstruction pipeline."""
        # WHY: Session reconstruction reads timeline events and
        # correlations. Without expected_tenant_id enforcement,
        # a session_id collision between tenants could return
        # another tenant's events. RLS enforces this at DB level;
        # the parameter enforces it at application level too.
        record = await persistence.get_session(
            request.session_id,
            expected_tenant_id=request.expected_tenant_id,
        )
        if record is None:
            return _ReconstructionPayload(
                status=SessionReconstructionStatus.NOT_FOUND,
                session=None,
                timeline=None,
                lineage=None,
                correlations=(),
            )

        session = record_to_session(record)

        try:
            timeline = await self._reconstruct_timeline(
                session_id=request.session_id,
                request=request,
                persistence=persistence,
            )
        except SessionReconstructionError as exc:
            return _ReconstructionPayload(
                status=SessionReconstructionStatus.DRIFT_DETECTED,
                session=session,
                timeline=None,
                lineage=session.lineage if request.include_lineage else None,
                correlations=(),
                error=str(exc),
            )

        correlations: tuple[SessionCorrelation, ...] = ()
        if request.include_correlations:
            correlations = await self._reconstruct_correlations(
                session_id=request.session_id,
                expected_tenant_id=request.expected_tenant_id,
                persistence=persistence,
            )

        applied_window = (
            request.as_of is not None
            or request.from_sequence is not None
            or request.to_sequence is not None
        )
        is_full = (
            timeline.length == session.sequence_head + 1
            and not applied_window
        )
        status = (
            SessionReconstructionStatus.PRISTINE
            if is_full
            else SessionReconstructionStatus.PARTIAL
        )

        return _ReconstructionPayload(
            status=status,
            session=session,
            timeline=timeline,
            lineage=(
                session.lineage if request.include_lineage else None
            ),
            correlations=correlations,
        )

    async def _reconstruct_timeline(
        self,
        *,
        session_id: SessionId,
        request: ReconstructSessionRequest,
        persistence: SessionPersistenceProtocol,
    ) -> SessionTimeline:
        page = await persistence.list_events(
            SessionEventQuery(
                session_id=session_id,
                from_sequence=request.from_sequence,
                to_sequence=request.to_sequence,
                occurred_before_or_at=request.as_of,
            ),
            expected_tenant_id=request.expected_tenant_id,
        )
        events: list[SessionTimelineEvent] = []
        prev_sequence: int | None = None
        for record in page.events:
            event = event_record_to_model(record)
            self._verify_event_id(event)
            if (
                prev_sequence is not None
                and event.sequence <= prev_sequence
            ):
                raise SessionReconstructionError(
                    f"non-monotonic event sequence during "
                    f"reconstruction: prev={prev_sequence}, "
                    f"current={event.sequence}"
                )
            events.append(
                # Replay events carry the RECONSTRUCTED continuity
                # mode tag — the substrate distinguishes events
                # appended live from events emitted during replay.
                SessionTimelineEvent(
                    event_id=event.event_id,
                    session_id=event.session_id,
                    sequence=event.sequence,
                    kind=event.kind,
                    continuity_mode=SessionContinuityMode.RECONSTRUCTED,
                    occurred_at=event.occurred_at,
                    recorded_at=event.recorded_at,
                    payload=dict(event.payload),
                    correlation_id=event.correlation_id,
                    annotation=event.annotation,
                )
            )
            prev_sequence = event.sequence

        head = events[-1].sequence if events else -1
        return SessionTimeline(
            session_id=session_id,
            events=tuple(events),
            head_sequence=head,
        )

    async def _reconstruct_correlations(
        self,
        *,
        session_id: SessionId,
        expected_tenant_id: str,
        persistence: SessionPersistenceProtocol,
    ) -> tuple[SessionCorrelation, ...]:
        page = await persistence.list_correlations(
            SessionCorrelationQuery(session_id=session_id),
            expected_tenant_id=expected_tenant_id,
        )
        return tuple(
            correlation_record_to_model(r) for r in page.correlations
        )

    @staticmethod
    def _verify_event_id(event: SessionTimelineEvent) -> None:
        expected = derive_event_id(
            session_id=event.session_id,
            sequence=event.sequence,
        )
        if expected != event.event_id:
            raise SessionReconstructionError(
                f"event id mismatch at sequence {event.sequence}: "
                f"expected={expected}, stored={event.event_id}"
            )


__all__ = ["SessionReconstructor"]
