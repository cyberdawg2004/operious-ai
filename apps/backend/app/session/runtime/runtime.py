"""`SessionRuntime` — continuity ledger.

Sprint N discipline:

* The runtime is a **continuity ledger**, not a workflow engine.
* All public methods are `async` and NEVER raise — failures fold
  onto the envelope.
* No public method invokes any sibling substrate. No public method
  schedules, routes, retries, escalates, plans, or auto-transitions.
* The runtime exposes EXACTLY these mutating surfaces:

  * `open_session(...)`         — create a new session.
  * `append_event(...)`         — append one timeline event.
  * `record_lifecycle(...)`     — explicit lifecycle reclassification.
  * `record_context(...)`       — bind / replace the context.
  * `record_correlation(...)`   — record a cross-substrate
                                    correlation observation.

  And these read-only surfaces:

  * `reconstruct(...)`          — historical reconstruction.
  * `get_session(...)`          — apex record lookup.
  * `get_timeline(...)`         — full / windowed timeline read.

  No others. The invariant test pins this surface.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Mapping
from dataclasses import replace as _dc_replace
from datetime import datetime, timezone
from typing import Any

from app.governance.capability import (
    GovernanceRuntime,
    OperationalAct,
    evaluate_capability_gate,
)
from app.core.deterministic_identity import derive_runtime_id
from app.identity import (
    AuthorityResolution,
    request_authority_resolution,
)
from app.session.contracts.requests import (
    AppendEventRequest,
    OpenSessionRequest,
    ReconstructSessionRequest,
    RecordContextRequest,
    RecordCorrelationRequest,
    RecordLifecycleRequest,
)
from app.session.contracts.results import (
    AppendEventResult,
    OpenSessionResult,
    ReconstructSessionResult,
    RecordContextResult,
    RecordCorrelationResult,
    RecordLifecycleResult,
)
from app.session.correlation.correlator import (
    build_correlation,
)
from app.session.envelopes import SessionEnvelope
from app.session.enums import (
    SessionContinuityMode,
    SessionEventKind,
    SessionLifecyclePhase,
)
from app.session.exceptions import (
    SessionLifecycleError,
    SessionNotFoundError,
    SessionPersistenceError,
    SessionValidationError,
)
from app.session.identity import (
    SessionCorrelationId,
    SessionEventId,
    SessionId,
    SessionReconstructionId,
    derive_correlation_id,
    derive_reconstruction_id,
    derive_session_id,
    derive_trace_id,
    generate_session_id,
    generate_trace_id,
)
from app.session.lifecycle.classifier import (
    is_terminal,
    next_phase_classification,
)
from app.session.lineage.tracker import (
    build_lineage_for_child,
    build_lineage_for_root,
)
from app.session.models.identity import SessionIdentity
from app.session.models.lifecycle import SessionLifecycle
from app.session.models.session import OperationalSession
from app.session.models.timeline import SessionTimeline as SessionTimeline
from app.session.models.timeline_event import (
    SessionTimelineEvent,
)
from app.session.persistence.repository import (
    SessionPersistenceProtocol,
)
from app.session.persistence.serializers import (
    correlation_to_record,
    event_record_to_model,
    event_to_record,
    record_to_session,
    session_to_record,
)
from app.session.reconstruction.reconstructor import (
    SessionReconstructor,
)
from app.session.registry.registry import SessionRegistry
from app.session.serializers.canonical import (
    canonicalize_payload,
)
from app.session.taxonomy import SessionMetadataKey
from app.session.timeline.builder import build_event
from app.session.traces.trace import (
    SessionTrace,
    SessionTraceKind,
)

_logger = logging.getLogger(__name__)
_RUNTIME_NAMESPACE = uuid.UUID("e4ed8a1a-13be-4ac1-bd19-1a2dbe506007")


class SessionRuntime:
    """Continuity ledger — append-only operational organism."""

    __slots__ = (
        "_persistence",
        "_registry",
        "_reconstructor",
        "_runtime_instance_id",
        "_sequence",
        "_capability_governance",
    )

    def __init__(
        self,
        *,
        persistence: SessionPersistenceProtocol,
        registry: SessionRegistry | None = None,
        reconstructor: SessionReconstructor | None = None,
        governance: GovernanceRuntime | None = None,
    ) -> None:
        self._persistence = persistence
        self._registry = registry or SessionRegistry()
        self._reconstructor = (
            reconstructor or SessionReconstructor()
        )
        self._runtime_instance_id = derive_runtime_id(
            namespace=_RUNTIME_NAMESPACE,
            tenant_id=None,
            seed_components=("session_runtime",),
        )
        self._sequence: int = 0
        # 2.75-\u03b1: capability legality gate. ``None`` keeps the
        # gate inert (test / dev). Production composition root pins
        # a configured ``GovernanceRuntime`` so every ``open_session``
        # is evaluated against ``OperationalAct.SESSION_OPEN``.
        self._capability_governance = governance

    # ─── Public read-only properties ────────────────────────────────

    @property
    def runtime_instance_id(self) -> uuid.UUID:
        return self._runtime_instance_id

    @property
    def persistence(self) -> SessionPersistenceProtocol:
        return self._persistence

    @property
    def registry(self) -> SessionRegistry:
        return self._registry

    # ─── open_session ───────────────────────────────────────────────

    async def open_session(
        self, request: OpenSessionRequest
    ) -> SessionEnvelope:
        started_at = datetime.now(tz=timezone.utc)
        t0 = time.perf_counter()
        # P2-A: collapse typed+legacy authority into a single
        # AuthorityResolution at the runtime boundary.
        resolution = request_authority_resolution(request)
        # 2.75-\u03b1: capability legality gate. Inert when
        # ``self._capability_governance`` is unconfigured (tests
        # / dev). When configured, an empty-capabilities authority
        # context produces DENY which folds into the existing
        # fail-fast envelope path.
        # 2.75-\u03b4: capture (decision_id, chain_id) from the gate
        # outcome and stamp them on the apex ``SessionTrace`` for
        # OPEN_SESSION calls. Joinable by id against the governance
        # repository — auditors reconstruct WHY this session was
        # allowed without re-evaluating the gate.
        gate_outcome = await evaluate_capability_gate(
            self._capability_governance,
            act=OperationalAct.SESSION_OPEN,
            authority=request.authority,
            resolution=resolution,
            actor="session_runtime",
        )
        if gate_outcome.denial is not None:
            return self._failed_envelope(
                kind=SessionTraceKind.OPEN_SESSION,
                session_id=None,
                started_at=started_at,
                t0=t0,
                error=gate_outcome.denial,
                request_correlation_id=request.correlation_id,
                request_request_id=request.request_id,
                governance_decision_id=gate_outcome.decision_id,
                governance_chain_id=gate_outcome.chain_id,
            )
        try:
            session_id = self._resolve_open_session_id(
                request, resolution=resolution
            )
            opened_at = (
                request.opened_at_override
                if request.opened_at_override is not None
                else started_at
            )
            if opened_at.tzinfo is None:
                raise SessionValidationError(
                    "open_session.opened_at must be timezone-aware"
                )
            identity = SessionIdentity(
                session_id=session_id,
                scope=request.scope,
                external_handle=request.external_handle,
                tenant_id=resolution.tenant_id,
                principal_id=request.principal_id,
            )
            if request.parent_session_id is not None:
                parent = await self._load_session(
                    request.parent_session_id
                )
                lineage = build_lineage_for_child(
                    session_id=session_id,
                    parent_lineage=parent.lineage,
                )
            else:
                lineage = build_lineage_for_root(
                    session_id=session_id
                )
            lifecycle = SessionLifecycle(
                phase=SessionLifecyclePhase.INITIATED,
                recorded_at=opened_at,
                reason=None,
            )
            session = OperationalSession(
                identity=identity,
                opened_at=opened_at,
                lifecycle=lifecycle,
                lineage=lineage,
                context=request.context,
                sequence_head=-1,
                revision=0,
            )

            opening_event = build_event(
                session_id=session_id,
                sequence=0,
                kind=SessionEventKind.SESSION_OPENED,
                continuity_mode=SessionContinuityMode.SYNCHRONOUS,
                occurred_at=opened_at,
                recorded_at=started_at,
                payload={
                    "scope": request.scope.value,
                    "external_handle": request.external_handle,
                    "tenant_id": resolution.tenant_id,
                    "principal_id": request.principal_id,
                    "tenant_authority_source": resolution.source.value,
                    "governance_decision_id": (
                        str(gate_outcome.decision_id)
                        if gate_outcome.decision_id is not None
                        else None
                    ),
                    "governance_chain_id": gate_outcome.chain_id,
                    "parent_session_id": (
                        str(request.parent_session_id)
                        if request.parent_session_id is not None
                        else None
                    ),
                    "lineage_depth": lineage.depth,
                    "context_present": (
                        request.context is not None
                    ),
                },
            )
            session = _dc_replace(
                session, sequence_head=0, revision=1
            )

            await self._persistence.save_session(
                session_to_record(session)
            )
            await self._persistence.save_event(
                event_to_record(opening_event)
            )
            await self._registry.register(session)
        except SessionLifecycleError as exc:
            return self._failed_envelope(
                kind=SessionTraceKind.OPEN_SESSION,
                session_id=None,
                started_at=started_at,
                t0=t0,
                error=exc,
                request_correlation_id=request.correlation_id,
                request_request_id=request.request_id,
            )
        except SessionValidationError as exc:
            return self._failed_envelope(
                kind=SessionTraceKind.OPEN_SESSION,
                session_id=None,
                started_at=started_at,
                t0=t0,
                error=exc,
                request_correlation_id=request.correlation_id,
                request_request_id=request.request_id,
            )
        except SessionNotFoundError as exc:
            return self._failed_envelope(
                kind=SessionTraceKind.OPEN_SESSION,
                session_id=None,
                started_at=started_at,
                t0=t0,
                error=exc,
                request_correlation_id=request.correlation_id,
                request_request_id=request.request_id,
            )
        except Exception as exc:  # noqa: BLE001
            _logger.exception(
                "session open failed; folding onto envelope"
            )
            return self._failed_envelope(
                kind=SessionTraceKind.OPEN_SESSION,
                session_id=None,
                started_at=started_at,
                t0=t0,
                error=exc,
                request_correlation_id=request.correlation_id,
                request_request_id=request.request_id,
            )

        ended_at = datetime.now(tz=timezone.utc)
        latency_ms = (time.perf_counter() - t0) * 1000.0
        sequence = self._next_sequence()
        result = OpenSessionResult(
            sequence=sequence,
            runtime_instance_id=self._runtime_instance_id,
            started_at=started_at,
            ended_at=ended_at,
            latency_ms=latency_ms,
            correlation_id=request.correlation_id,
            request_id=request.request_id,
            session=session,
            metadata=self._open_session_metadata(
                request=request,
                session=session,
            ),
        )
        trace = self._build_trace(
            kind=SessionTraceKind.OPEN_SESSION,
            session_id=session.identity.session_id,
            started_at=started_at,
            ended_at=ended_at,
            latency_ms=latency_ms,
            sequence=sequence,
            request_correlation_id=request.correlation_id,
            request_request_id=request.request_id,
            tenant_id=session.identity.tenant_id,
            principal_id=session.identity.principal_id,
            tenant_authority_source=resolution.source.value,
            governance_decision_id=gate_outcome.decision_id,
            governance_chain_id=gate_outcome.chain_id,
        )
        return SessionEnvelope(trace=trace, result=result)

    # ─── append_event ───────────────────────────────────────────────

    async def append_event(
        self, request: AppendEventRequest
    ) -> SessionEnvelope:
        # 2.5-B: thread ``request.correlation_id`` (a free-form string
        # cross-substrate handle) into the persisted
        # ``SessionTimelineEvent.correlation_id`` (a typed UUID5
        # ``SessionCorrelationId``) via ``derive_correlation_id``.
        # The session substrate is the canonical chronology fabric;
        # dropping the request correlation here breaks the
        # forensic-audit join from request to persisted event.
        # ``kind="request_correlation"`` is namespace-distinct from
        # every value in ``SessionCorrelationKind`` so this projection
        # never collides with a record_correlation()-emitted id.
        derived_correlation: SessionCorrelationId | None = None
        if request.correlation_id:
            derived_correlation = derive_correlation_id(
                session_id=request.session_id,
                kind="request_correlation",
                external_id=request.correlation_id,
            )
        return await self._append_generic(
            session_id=request.session_id,
            kind=request.kind,
            occurred_at=request.occurred_at,
            continuity_mode=request.continuity_mode,
            payload=request.payload,
            annotation=request.annotation,
            correlation_id=derived_correlation,
            request_correlation_id=request.correlation_id,
            request_request_id=request.request_id,
            extra_metadata=dict(request.metadata),
            trace_kind=SessionTraceKind.APPEND_EVENT,
            external_correlation_id=request.external_correlation_id,
            idempotency_key=request.idempotency_key,
        )

    # ─── record_lifecycle ───────────────────────────────────────────

    async def record_lifecycle(
        self, request: RecordLifecycleRequest
    ) -> SessionEnvelope:
        started_at = datetime.now(tz=timezone.utc)
        t0 = time.perf_counter()
        try:
            session = await self._load_session(request.session_id)
            current = session.lifecycle.phase
            proposed = request.phase
            if is_terminal(current) and proposed is not current:
                raise SessionLifecycleError(
                    f"cannot reclassify terminal session "
                    f"({current.value} → {proposed.value})"
                )
            recorded_at = (
                request.recorded_at
                if request.recorded_at is not None
                else started_at
            )
            event_kind = next_phase_classification(
                current=current, proposed=proposed
            )
            event = self._build_next_event(
                session=session,
                kind=event_kind,
                occurred_at=recorded_at,
                recorded_at=started_at,
                continuity_mode=SessionContinuityMode.SYNCHRONOUS,
                payload={
                    "previous_phase": current.value,
                    "new_phase": proposed.value,
                    "reason": request.reason,
                },
                annotation=request.reason,
            )
            new_lifecycle = SessionLifecycle(
                phase=proposed,
                recorded_at=recorded_at,
                reason=request.reason,
            )
            updated_session = _dc_replace(
                session,
                lifecycle=new_lifecycle,
                sequence_head=event.sequence,
                revision=session.revision + 1,
            )
            await self._persist_session_update(
                session=updated_session, event=event
            )
        except (
            SessionLifecycleError,
            SessionValidationError,
            SessionNotFoundError,
        ) as exc:
            return self._failed_envelope(
                kind=SessionTraceKind.RECORD_LIFECYCLE,
                session_id=request.session_id,
                started_at=started_at,
                t0=t0,
                error=exc,
                request_correlation_id=request.correlation_id,
                request_request_id=request.request_id,
            )
        except Exception as exc:  # noqa: BLE001
            _logger.exception(
                "record_lifecycle failed; folding onto envelope"
            )
            return self._failed_envelope(
                kind=SessionTraceKind.RECORD_LIFECYCLE,
                session_id=request.session_id,
                started_at=started_at,
                t0=t0,
                error=exc,
                request_correlation_id=request.correlation_id,
                request_request_id=request.request_id,
            )

        ended_at = datetime.now(tz=timezone.utc)
        latency_ms = (time.perf_counter() - t0) * 1000.0
        sequence = self._next_sequence()
        result = RecordLifecycleResult(
            sequence=sequence,
            runtime_instance_id=self._runtime_instance_id,
            started_at=started_at,
            ended_at=ended_at,
            latency_ms=latency_ms,
            correlation_id=request.correlation_id,
            request_id=request.request_id,
            event=event,
            session=updated_session,
        )
        trace = self._build_trace(
            kind=SessionTraceKind.RECORD_LIFECYCLE,
            session_id=request.session_id,
            event_id=event.event_id,
            started_at=started_at,
            ended_at=ended_at,
            latency_ms=latency_ms,
            sequence=sequence,
            request_correlation_id=request.correlation_id,
            request_request_id=request.request_id,
            tenant_id=updated_session.identity.tenant_id,
            principal_id=updated_session.identity.principal_id,
        )
        return SessionEnvelope(trace=trace, result=result)

    # ─── record_context ─────────────────────────────────────────────

    async def record_context(
        self, request: RecordContextRequest
    ) -> SessionEnvelope:
        started_at = datetime.now(tz=timezone.utc)
        t0 = time.perf_counter()
        try:
            session = await self._load_session(request.session_id)
            self._reject_terminal(session)
            recorded_at = (
                request.recorded_at
                if request.recorded_at is not None
                else started_at
            )
            event = self._build_next_event(
                session=session,
                kind=SessionEventKind.CONTEXT_ATTACHED,
                occurred_at=recorded_at,
                recorded_at=started_at,
                continuity_mode=SessionContinuityMode.SYNCHRONOUS,
                payload={
                    "environment": request.context.environment,
                    "labels": list(request.context.labels),
                    "attributes": dict(
                        request.context.attributes
                    ),
                    "notes": request.context.notes,
                },
                annotation=None,
            )
            updated_session = _dc_replace(
                session,
                context=request.context,
                sequence_head=event.sequence,
                revision=session.revision + 1,
            )
            await self._persist_session_update(
                session=updated_session, event=event
            )
        except (
            SessionLifecycleError,
            SessionValidationError,
            SessionNotFoundError,
        ) as exc:
            return self._failed_envelope(
                kind=SessionTraceKind.RECORD_CONTEXT,
                session_id=request.session_id,
                started_at=started_at,
                t0=t0,
                error=exc,
                request_correlation_id=request.correlation_id,
                request_request_id=request.request_id,
            )
        except Exception as exc:  # noqa: BLE001
            _logger.exception(
                "record_context failed; folding onto envelope"
            )
            return self._failed_envelope(
                kind=SessionTraceKind.RECORD_CONTEXT,
                session_id=request.session_id,
                started_at=started_at,
                t0=t0,
                error=exc,
                request_correlation_id=request.correlation_id,
                request_request_id=request.request_id,
            )

        ended_at = datetime.now(tz=timezone.utc)
        latency_ms = (time.perf_counter() - t0) * 1000.0
        sequence = self._next_sequence()
        result = RecordContextResult(
            sequence=sequence,
            runtime_instance_id=self._runtime_instance_id,
            started_at=started_at,
            ended_at=ended_at,
            latency_ms=latency_ms,
            correlation_id=request.correlation_id,
            request_id=request.request_id,
            event=event,
            session=updated_session,
        )
        trace = self._build_trace(
            kind=SessionTraceKind.RECORD_CONTEXT,
            session_id=request.session_id,
            event_id=event.event_id,
            started_at=started_at,
            ended_at=ended_at,
            latency_ms=latency_ms,
            sequence=sequence,
            request_correlation_id=request.correlation_id,
            request_request_id=request.request_id,
            tenant_id=updated_session.identity.tenant_id,
            principal_id=updated_session.identity.principal_id,
        )
        return SessionEnvelope(trace=trace, result=result)

    # ─── record_correlation ─────────────────────────────────────────

    async def record_correlation(
        self, request: RecordCorrelationRequest
    ) -> SessionEnvelope:
        started_at = datetime.now(tz=timezone.utc)
        t0 = time.perf_counter()
        try:
            session = await self._load_session(request.session_id)
            self._reject_terminal(session)
            recorded_at = (
                request.recorded_at
                if request.recorded_at is not None
                else started_at
            )
            correlation = build_correlation(
                session_id=request.session_id,
                kind=request.kind,
                external_id=request.external_id,
                recorded_at=recorded_at,
                external_correlation_id=request.external_correlation_id,
                annotation=request.annotation,
                attributes=request.attributes,
            )
            event = self._build_next_event(
                session=session,
                kind=SessionEventKind.CORRELATION_RECORDED,
                occurred_at=recorded_at,
                recorded_at=started_at,
                continuity_mode=SessionContinuityMode.SYNCHRONOUS,
                payload={
                    "correlation_kind": request.kind.value,
                    "external_id": request.external_id,
                    "external_correlation_id": (
                        request.external_correlation_id
                    ),
                    "annotation": request.annotation,
                    "attributes": dict(request.attributes),
                },
                annotation=request.annotation,
                correlation_id=correlation.correlation_id,
            )
            updated_session = _dc_replace(
                session,
                sequence_head=event.sequence,
                revision=session.revision + 1,
            )
            await self._persistence.save_correlation(
                correlation_to_record(correlation)
            )
            await self._persist_session_update(
                session=updated_session, event=event
            )
        except (
            SessionLifecycleError,
            SessionValidationError,
            SessionNotFoundError,
        ) as exc:
            return self._failed_envelope(
                kind=SessionTraceKind.RECORD_CORRELATION,
                session_id=request.session_id,
                started_at=started_at,
                t0=t0,
                error=exc,
                request_correlation_id=request.correlation_id,
                request_request_id=request.request_id,
            )
        except Exception as exc:  # noqa: BLE001
            _logger.exception(
                "record_correlation failed; folding onto envelope"
            )
            return self._failed_envelope(
                kind=SessionTraceKind.RECORD_CORRELATION,
                session_id=request.session_id,
                started_at=started_at,
                t0=t0,
                error=exc,
                request_correlation_id=request.correlation_id,
                request_request_id=request.request_id,
            )

        ended_at = datetime.now(tz=timezone.utc)
        latency_ms = (time.perf_counter() - t0) * 1000.0
        sequence = self._next_sequence()
        result = RecordCorrelationResult(
            sequence=sequence,
            runtime_instance_id=self._runtime_instance_id,
            started_at=started_at,
            ended_at=ended_at,
            latency_ms=latency_ms,
            correlation_id=request.correlation_id,
            request_id=request.request_id,
            correlation=correlation,
            event=event,
            session=updated_session,
        )
        trace = self._build_trace(
            kind=SessionTraceKind.RECORD_CORRELATION,
            session_id=request.session_id,
            event_id=event.event_id,
            started_at=started_at,
            ended_at=ended_at,
            latency_ms=latency_ms,
            sequence=sequence,
            request_correlation_id=request.correlation_id,
            request_request_id=request.request_id,
            tenant_id=updated_session.identity.tenant_id,
            principal_id=updated_session.identity.principal_id,
        )
        return SessionEnvelope(trace=trace, result=result)

    # ─── reconstruct ────────────────────────────────────────────────

    async def reconstruct(
        self, request: ReconstructSessionRequest
    ) -> SessionEnvelope:
        started_at = datetime.now(tz=timezone.utc)
        t0 = time.perf_counter()
        reconstruction_id = derive_reconstruction_id(
            seed=(
                f"{request.session_id}|"
                f"{request.as_of.isoformat() if request.as_of else ''}|"
                f"{request.from_sequence}|{request.to_sequence}|"
                f"{request.include_lineage}|{request.include_correlations}"
            )
        )
        try:
            payload = await self._reconstructor.reconstruct(
                request=request,
                persistence=self._persistence,
            )
        except Exception as exc:  # noqa: BLE001
            _logger.exception(
                "reconstruct failed; folding onto envelope"
            )
            return self._failed_envelope(
                kind=SessionTraceKind.RECONSTRUCT,
                session_id=request.session_id,
                started_at=started_at,
                t0=t0,
                error=exc,
                request_correlation_id=request.correlation_id,
                request_request_id=request.request_id,
            )

        ended_at = datetime.now(tz=timezone.utc)
        latency_ms = (time.perf_counter() - t0) * 1000.0
        sequence = self._next_sequence()
        result = ReconstructSessionResult(
            sequence=sequence,
            runtime_instance_id=self._runtime_instance_id,
            started_at=started_at,
            ended_at=ended_at,
            latency_ms=latency_ms,
            correlation_id=request.correlation_id,
            request_id=request.request_id,
            reconstruction_id=reconstruction_id,
            status=payload.status,
            session=payload.session,
            timeline=payload.timeline,
            lineage=payload.lineage,
            correlations=payload.correlations,
        )
        trace = self._build_trace(
            kind=SessionTraceKind.RECONSTRUCT,
            session_id=request.session_id,
            started_at=started_at,
            ended_at=ended_at,
            latency_ms=latency_ms,
            sequence=sequence,
            request_correlation_id=request.correlation_id,
            request_request_id=request.request_id,
            tenant_id=(
                payload.session.identity.tenant_id
                if payload.session is not None
                else None
            ),
            principal_id=(
                payload.session.identity.principal_id
                if payload.session is not None
                else None
            ),
            error=payload.error,
            reconstruction_id=reconstruction_id,
        )
        return SessionEnvelope(trace=trace, result=result)

    # ─── read-only lookups ──────────────────────────────────────────

    async def get_session(
        self,
        session_id: SessionId,
        *,
        expected_tenant_id: str | None = None,
    ) -> SessionEnvelope:
        """Apex-record lookup. Tenant-scoped when ``expected_tenant_id``
        is supplied — sessions belonging to a different tenant are
        invisible to the caller (Wedge 2.75-ε)."""
        started_at = datetime.now(tz=timezone.utc)
        t0 = time.perf_counter()
        try:
            session = await self._load_session(
                session_id, expected_tenant_id=expected_tenant_id
            )
        except SessionNotFoundError as exc:
            return self._failed_envelope(
                kind=SessionTraceKind.LOOKUP,
                session_id=session_id,
                started_at=started_at,
                t0=t0,
                error=exc,
            )
        except Exception as exc:  # noqa: BLE001
            _logger.exception(
                "get_session failed; folding onto envelope"
            )
            return self._failed_envelope(
                kind=SessionTraceKind.LOOKUP,
                session_id=session_id,
                started_at=started_at,
                t0=t0,
                error=exc,
            )
        ended_at = datetime.now(tz=timezone.utc)
        latency_ms = (time.perf_counter() - t0) * 1000.0
        sequence = self._next_sequence()
        return SessionEnvelope(
            trace=self._build_trace(
                kind=SessionTraceKind.LOOKUP,
                session_id=session_id,
                started_at=started_at,
                ended_at=ended_at,
                latency_ms=latency_ms,
                sequence=sequence,
                request_correlation_id=None,
                request_request_id=None,
                tenant_id=session.identity.tenant_id,
                principal_id=session.identity.principal_id,
            ),
            result=session,
        )

    async def get_timeline(
        self, session_id: SessionId
    ) -> SessionEnvelope:
        request = ReconstructSessionRequest(
            session_id=session_id,
            include_lineage=False,
            include_correlations=False,
        )
        return await self.reconstruct(request)

    # ─── Internal helpers ────────────────────────────────────────────

    def _next_sequence(self) -> int:
        self._sequence += 1
        return self._sequence

    def _resolve_open_session_id(
        self,
        request: OpenSessionRequest,
        *,
        resolution: AuthorityResolution,
    ) -> SessionId:
        if request.session_id_override is not None:
            return request.session_id_override
        if request.opened_at_override is not None:
            return derive_session_id(
                scope=request.scope.value,
                tenant_id=resolution.tenant_id,
                principal_id=request.principal_id,
                external_handle=(
                    f"{request.external_handle}|"
                    f"{request.opened_at_override.isoformat()}"
                ),
            )
        return generate_session_id()

    async def _load_session(
        self,
        session_id: SessionId,
        *,
        expected_tenant_id: str | None = None,
    ) -> OperationalSession:
        cached = await self._registry.get(session_id)
        if cached is not None:
            # 2.75-ε: registry-cached sessions still honour the
            # tenant-scope check. Without it a tenant could see a
            # rival's session by virtue of the warm registry.
            if (
                expected_tenant_id is not None
                and cached.identity.tenant_id != expected_tenant_id
            ):
                raise SessionNotFoundError(
                    f"unknown session: {session_id}"
                )
            return cached
        record = await self._persistence.get_session(
            session_id, expected_tenant_id=expected_tenant_id
        )
        if record is None:
            raise SessionNotFoundError(
                f"unknown session: {session_id}"
            )
        session = record_to_session(record)
        # Best-effort registry hydration — never fatal.
        try:
            await self._registry.register(session)
        except Exception:  # noqa: BLE001
            pass
        return session

    @staticmethod
    def _reject_terminal(
        session: OperationalSession,
    ) -> None:
        if is_terminal(session.lifecycle.phase):
            raise SessionLifecycleError(
                f"session is terminal ({session.lifecycle.phase.value});"
                " no further appends accepted"
            )

    def _build_next_event(
        self,
        *,
        session: OperationalSession,
        kind: SessionEventKind,
        occurred_at: datetime,
        recorded_at: datetime,
        continuity_mode: SessionContinuityMode,
        payload: Mapping[str, Any] | None,
        annotation: str | None,
        correlation_id: SessionCorrelationId | None = None,
        idempotency_key: str | None = None,
    ) -> SessionTimelineEvent:
        if occurred_at.tzinfo is None:
            raise SessionValidationError(
                "occurred_at must be timezone-aware"
            )
        if recorded_at.tzinfo is None:
            raise SessionValidationError(
                "recorded_at must be timezone-aware"
            )
        return build_event(
            session_id=session.identity.session_id,
            sequence=session.sequence_head + 1,
            kind=kind,
            continuity_mode=continuity_mode,
            occurred_at=occurred_at,
            recorded_at=recorded_at,
            payload=canonicalize_payload(payload or {}),
            correlation_id=correlation_id,
            annotation=annotation,
            idempotency_key=idempotency_key,
        )

    async def _persist_session_update(
        self,
        *,
        session: OperationalSession,
        event: SessionTimelineEvent,
    ) -> None:
        await self._persistence.save_event(
            event_to_record(event)
        )
        await self._persistence.save_session(
            session_to_record(session)
        )
        await self._registry.update(session)

    async def _append_generic(
        self,
        *,
        session_id: SessionId,
        kind: SessionEventKind,
        occurred_at: datetime,
        continuity_mode: SessionContinuityMode,
        payload,  # type: ignore[no-untyped-def]
        annotation: str | None,
        correlation_id,  # type: ignore[no-untyped-def]
        request_correlation_id: str | None,
        request_request_id: str | None,
        extra_metadata: dict[str, object],
        trace_kind: SessionTraceKind,
        external_correlation_id: str | None,
        idempotency_key: str | None = None,
    ) -> SessionEnvelope:
        started_at = datetime.now(tz=timezone.utc)
        t0 = time.perf_counter()
        try:
            session = await self._load_session(session_id)
            if idempotency_key is not None:
                existing_record = (
                    await self._persistence.get_event_by_idempotency_key(
                        session_id=session_id,
                        idempotency_key=idempotency_key,
                    )
                )
                if existing_record is not None:
                    event = event_record_to_model(existing_record)
                    return self._append_event_replay_envelope(
                        trace_kind=trace_kind,
                        session=session,
                        event=event,
                        started_at=started_at,
                        t0=t0,
                        request_correlation_id=request_correlation_id,
                        request_request_id=request_request_id,
                        idempotency_key=idempotency_key,
                    )
            self._reject_terminal(session)
            event = self._build_next_event(
                session=session,
                kind=kind,
                occurred_at=occurred_at,
                recorded_at=started_at,
                continuity_mode=continuity_mode,
                payload={
                    **dict(payload or {}),
                    "external_correlation_id": (
                        external_correlation_id
                    ),
                },
                annotation=annotation,
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
            )
            updated_session = _dc_replace(
                session,
                sequence_head=event.sequence,
                revision=session.revision + 1,
            )
            try:
                await self._persist_session_update(
                    session=updated_session, event=event
                )
            except SessionPersistenceError:
                if idempotency_key is None:
                    raise
                existing_record = (
                    await self._persistence.get_event_by_idempotency_key(
                        session_id=session_id,
                        idempotency_key=idempotency_key,
                    )
                )
                if existing_record is None:
                    raise
                event = event_record_to_model(existing_record)
                replay_session = await self._load_persisted_session(
                    session_id=session_id,
                    fallback=session,
                )
                return self._append_event_replay_envelope(
                    trace_kind=trace_kind,
                    session=replay_session,
                    event=event,
                    started_at=started_at,
                    t0=t0,
                    request_correlation_id=request_correlation_id,
                    request_request_id=request_request_id,
                    idempotency_key=idempotency_key,
                )
        except (
            SessionLifecycleError,
            SessionValidationError,
            SessionNotFoundError,
        ) as exc:
            return self._failed_envelope(
                kind=trace_kind,
                session_id=session_id,
                started_at=started_at,
                t0=t0,
                error=exc,
                request_correlation_id=request_correlation_id,
                request_request_id=request_request_id,
            )
        except Exception as exc:  # noqa: BLE001
            _logger.exception(
                "append_event failed; folding onto envelope"
            )
            return self._failed_envelope(
                kind=trace_kind,
                session_id=session_id,
                started_at=started_at,
                t0=t0,
                error=exc,
                request_correlation_id=request_correlation_id,
                request_request_id=request_request_id,
            )

        ended_at = datetime.now(tz=timezone.utc)
        latency_ms = (time.perf_counter() - t0) * 1000.0
        sequence = self._next_sequence()
        result = AppendEventResult(
            sequence=sequence,
            runtime_instance_id=self._runtime_instance_id,
            started_at=started_at,
            ended_at=ended_at,
            latency_ms=latency_ms,
            correlation_id=request_correlation_id,
            request_id=request_request_id,
            event=event,
            session=updated_session,
            metadata=dict(extra_metadata),
        )
        trace = self._build_trace(
            kind=trace_kind,
            session_id=session_id,
            event_id=event.event_id,
            started_at=started_at,
            ended_at=ended_at,
            latency_ms=latency_ms,
            sequence=sequence,
            request_correlation_id=request_correlation_id,
            request_request_id=request_request_id,
            tenant_id=updated_session.identity.tenant_id,
            principal_id=updated_session.identity.principal_id,
        )
        return SessionEnvelope(trace=trace, result=result)

    def _append_event_replay_envelope(
        self,
        *,
        trace_kind: SessionTraceKind,
        session: OperationalSession,
        event: SessionTimelineEvent,
        started_at: datetime,
        t0: float,
        request_correlation_id: str | None,
        request_request_id: str | None,
        idempotency_key: str,
    ) -> SessionEnvelope:
        ended_at = datetime.now(tz=timezone.utc)
        latency_ms = (time.perf_counter() - t0) * 1000.0
        sequence = self._next_sequence()
        result = AppendEventResult(
            sequence=sequence,
            runtime_instance_id=self._runtime_instance_id,
            started_at=started_at,
            ended_at=ended_at,
            latency_ms=latency_ms,
            correlation_id=request_correlation_id,
            request_id=request_request_id,
            event=event,
            session=session,
            metadata={
                "idempotency_key": idempotency_key,
                "idempotent_replay": True,
            },
        )
        trace = self._build_trace(
            kind=trace_kind,
            session_id=session.identity.session_id,
            event_id=event.event_id,
            started_at=started_at,
            ended_at=ended_at,
            latency_ms=latency_ms,
            sequence=sequence,
            request_correlation_id=request_correlation_id,
            request_request_id=request_request_id,
            tenant_id=session.identity.tenant_id,
            principal_id=session.identity.principal_id,
        )
        return SessionEnvelope(trace=trace, result=result)

    async def _load_persisted_session(
        self,
        *,
        session_id: SessionId,
        fallback: OperationalSession,
    ) -> OperationalSession:
        record = await self._persistence.get_session(session_id)
        if record is None:
            return fallback
        session = record_to_session(record)
        try:
            await self._registry.update(session)
        except Exception:  # noqa: BLE001
            pass
        return session

    def _build_trace(  # type: ignore[no-untyped-def]
        self,
        *,
        kind: SessionTraceKind,
        session_id: SessionId | None,
        started_at: datetime,
        ended_at: datetime,
        latency_ms: float,
        sequence: int,
        request_correlation_id: str | None,
        request_request_id: str | None,
        tenant_id: str | None = None,
        principal_id: str | None = None,
        event_id: SessionEventId | None = None,
        reconstruction_id: SessionReconstructionId | None = None,
        error: str | None = None,
        tenant_authority_source: str | None = None,
        governance_decision_id: uuid.UUID | None = None,
        governance_chain_id: str | None = None,
    ) -> SessionTrace:
        # Replay determinism (Core Law 2): when the request carries a
        # correlation anchor, derive `trace_id` deterministically from
        # `(kind, correlation_id, request_id, runtime_instance_id,
        # sequence)` so the same emission is idempotently identified.
        # Without a correlation anchor we fall back to UUID4 — there
        # is no replayable lineage to anchor against.
        if request_correlation_id:
            trace_id = derive_trace_id(
                seed=(
                    f"{kind.value}|{request_correlation_id}|"
                    f"{request_request_id or ''}|"
                    f"{self._runtime_instance_id}|{sequence}"
                )
            )
        else:
            trace_id = generate_trace_id()
        return SessionTrace(
            trace_id=trace_id,
            kind=kind,
            runtime_instance_id=self._runtime_instance_id,
            sequence=sequence,
            started_at=started_at,
            ended_at=ended_at,
            latency_ms=latency_ms,
            session_id=session_id,
            event_id=event_id,
            reconstruction_id=reconstruction_id,
            correlation_id=request_correlation_id,
            request_id=request_request_id,
            tenant_id=tenant_id,
            principal_id=principal_id,
            error=error,
            tenant_authority_source=tenant_authority_source,
            governance_decision_id=governance_decision_id,
            governance_chain_id=governance_chain_id,
        )

    def _failed_envelope(  # type: ignore[no-untyped-def]
        self,
        *,
        kind: SessionTraceKind,
        session_id: SessionId | None,
        started_at: datetime,
        t0: float,
        error: BaseException,
        request_correlation_id: str | None = None,
        request_request_id: str | None = None,
        governance_decision_id: uuid.UUID | None = None,
        governance_chain_id: str | None = None,
    ) -> SessionEnvelope:
        # Chronology integrity (Core Law 3): every emitted envelope
        # MUST consume a fresh monotonic sequence inside the runtime
        # instance. Failures are emissions too — reusing the prior
        # success's sequence is a silent chronology fork.
        ended_at = datetime.now(tz=timezone.utc)
        latency_ms = (time.perf_counter() - t0) * 1000.0
        sequence = self._next_sequence()
        trace = self._build_trace(
            kind=kind,
            session_id=session_id,
            started_at=started_at,
            ended_at=ended_at,
            latency_ms=latency_ms,
            sequence=sequence,
            request_correlation_id=request_correlation_id,
            request_request_id=request_request_id,
            error=f"{error.__class__.__name__}: {error}",
            governance_decision_id=governance_decision_id,
            governance_chain_id=governance_chain_id,
        )
        return SessionEnvelope(
            trace=trace, result=None, error=error
        )

    @staticmethod
    def _open_session_metadata(
        *,
        request: OpenSessionRequest,
        session: OperationalSession,
    ) -> dict[str, object]:
        meta: dict[str, object] = dict(request.metadata)
        meta[SessionMetadataKey.SESSION_ID.value] = str(
            session.identity.session_id
        )
        meta[SessionMetadataKey.SCOPE.value] = (
            session.identity.scope.value
        )
        if session.identity.tenant_id:
            meta[SessionMetadataKey.TENANT_ID.value] = (
                session.identity.tenant_id
            )
        if session.identity.principal_id:
            meta[SessionMetadataKey.PRINCIPAL_ID.value] = (
                session.identity.principal_id
            )
        meta[SessionMetadataKey.EXTERNAL_HANDLE.value] = (
            session.identity.external_handle
        )
        meta[SessionMetadataKey.LINEAGE_ID.value] = str(
            session.lineage.lineage_id
        )
        meta[SessionMetadataKey.LIFECYCLE_PHASE.value] = (
            session.lifecycle.phase.value
        )
        meta[SessionMetadataKey.OPENED_AT.value] = (
            session.opened_at.isoformat()
        )
        return meta




__all__ = ["SessionRuntime"]
