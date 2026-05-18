"""`CommunicationRuntime` — APPROVED-pattern retrieval + registration.

Discipline:

* `register_pattern()` requires an `ApprovalRecord` with
  ``decision == APPROVED``. The substrate refuses to register
  unapproved patterns.
* `retrieve_patterns()` returns deterministic match scores over
  the **registered** (i.e. APPROVED) catalogue. It NEVER
  invents a pattern at runtime.
* The runtime never auto-applies a pattern. It returns
  candidates; the caller (a deterministic execution runtime)
  decides which one to actually use.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone

from app.identity import request_authority_resolution
from app.organizational_intelligence.contracts.requests import (
    RegisterCommunicationPatternRequest,
    RetrieveCommunicationPatternsRequest,
)
from app.organizational_intelligence.contracts.results import (
    RegisterCommunicationPatternResult,
    RetrieveCommunicationPatternsResult,
)
from app.organizational_intelligence.envelopes import (
    IntelligenceEnvelope,
)
from app.organizational_intelligence.enums import (
    IntelligenceTraceKind,
)
from app.organizational_intelligence.exceptions import (
    IntelligenceError,
    IntelligenceValidationError,
)
from app.organizational_intelligence.governance.approval_gate import (
    require_approval_for_registration,
)
from app.organizational_intelligence.identity import (
    derive_communication_pattern_id,
    generate_trace_id,
)
from app.organizational_intelligence.models.communication import (
    CommunicationPattern,
    CommunicationRetrievalCandidate,
)
from app.organizational_intelligence.persistence.queries import (
    CommunicationPatternQuery,
)
from app.organizational_intelligence.persistence.repository import (
    IntelligencePersistenceProtocol,
)
from app.organizational_intelligence.serializers.canonical import (
    canonicalize_attributes,
)
from app.organizational_intelligence.supervision.scoring import (
    score_communication_match,
)
from app.organizational_intelligence.traces.trace import (
    IntelligenceTrace,
)

_logger = logging.getLogger(__name__)

_TARGET_KIND = "communication_pattern"


class CommunicationRuntime:
    """Approved-pattern registration + retrieval runtime."""

    __slots__ = (
        "_persistence",
        "_runtime_instance_id",
        "_sequence",
    )

    def __init__(
        self,
        *,
        persistence: IntelligencePersistenceProtocol,
    ) -> None:
        self._persistence = persistence
        self._runtime_instance_id = uuid.uuid4()
        self._sequence = 0

    @property
    def runtime_instance_id(self) -> uuid.UUID:
        return self._runtime_instance_id

    # ─── register ───────────────────────────────────────────────────

    async def register_pattern(
        self, request: RegisterCommunicationPatternRequest
    ) -> IntelligenceEnvelope:
        started_at = datetime.now(tz=timezone.utc)
        t0 = time.perf_counter()
        # P2-A: singular authority resolution.
        resolution = request_authority_resolution(request)
        try:
            if not request.handle:
                raise IntelligenceValidationError(
                    "register_pattern.handle must be non-empty"
                )
            if not request.body:
                raise IntelligenceValidationError(
                    "register_pattern.body must be non-empty"
                )
            if not request.applicable_classes:
                raise IntelligenceValidationError(
                    "register_pattern.applicable_classes must be "
                    "non-empty"
                )
            require_approval_for_registration(
                approval=request.approval,
                target_kind=_TARGET_KIND,
            )
            pattern_id = derive_communication_pattern_id(
                tenant_id=resolution.tenant_id,
                pattern_handle=request.handle,
            )
            pattern = CommunicationPattern(
                pattern_id=pattern_id,
                tenant_id=resolution.tenant_id,
                scope=request.scope,
                kind=request.kind,
                handle=request.handle,
                body=request.body,
                applicable_classes=tuple(
                    sorted(
                        set(request.applicable_classes),
                        key=lambda c: c.value,
                    )
                ),
                approval_id=request.approval.approval_id,
                registered_at=started_at,
                author_handle=request.author_handle,
                metadata=canonicalize_attributes(
                    request.metadata
                ),
            )
            await self._persistence.save_approval(request.approval)
            await self._persistence.save_communication_pattern(
                pattern
            )
        except IntelligenceError as exc:
            return self._failed(
                kind=IntelligenceTraceKind.COMMUNICATION_REGISTER,
                started_at=started_at,
                t0=t0,
                error=exc,
                correlation_id=request.correlation_id,
                request_id=request.request_id,
                tenant_id=resolution.tenant_id,
                tenant_authority_source=resolution.source.value,
            )
        except Exception as exc:  # noqa: BLE001
            _logger.exception(
                "register_pattern failed; folding onto envelope"
            )
            return self._failed(
                kind=IntelligenceTraceKind.COMMUNICATION_REGISTER,
                started_at=started_at,
                t0=t0,
                error=exc,
                correlation_id=request.correlation_id,
                request_id=request.request_id,
                tenant_id=resolution.tenant_id,
                tenant_authority_source=resolution.source.value,
            )

        ended_at = datetime.now(tz=timezone.utc)
        latency = (time.perf_counter() - t0) * 1000.0
        sequence = self._next_sequence()
        result = RegisterCommunicationPatternResult(
            sequence=sequence,
            runtime_instance_id=self._runtime_instance_id,
            started_at=started_at,
            ended_at=ended_at,
            latency_ms=latency,
            correlation_id=request.correlation_id,
            request_id=request.request_id,
            pattern=pattern,
            approval=request.approval,
        )
        return IntelligenceEnvelope(
            trace=self._trace(
                kind=IntelligenceTraceKind.COMMUNICATION_REGISTER,
                started_at=started_at,
                ended_at=ended_at,
                latency=latency,
                sequence=sequence,
                correlation_id=request.correlation_id,
                request_id=request.request_id,
                tenant_id=resolution.tenant_id,
                tenant_authority_source=resolution.source.value,
            ),
            result=result,
        )

    # ─── retrieve ───────────────────────────────────────────────────

    async def retrieve_patterns(
        self, request: RetrieveCommunicationPatternsRequest
    ) -> IntelligenceEnvelope:
        started_at = datetime.now(tz=timezone.utc)
        t0 = time.perf_counter()
        # P2-A: singular authority resolution.
        resolution = request_authority_resolution(request)
        try:
            if request.limit < 1:
                raise IntelligenceValidationError(
                    "retrieve_patterns.limit must be >= 1"
                )
            page = await self._persistence.list_communication_patterns(
                CommunicationPatternQuery(
                    tenant_id=resolution.tenant_id,
                    scope=request.scope,
                    applicable_class=request.primary_class,
                )
            )
            scored: list[CommunicationRetrievalCandidate] = []
            for pattern in page.patterns:
                if (
                    request.desired_kinds
                    and pattern.kind not in request.desired_kinds
                ):
                    continue
                score, reason = score_communication_match(
                    primary_class=request.primary_class,
                    pattern=pattern,
                )
                if score <= 0.0:
                    continue
                scored.append(
                    CommunicationRetrievalCandidate(
                        pattern=pattern,
                        score=score,
                        match_reason=reason,
                    )
                )
            scored.sort(
                key=lambda c: (
                    -c.score,
                    c.pattern.handle,
                    str(c.pattern.pattern_id),
                )
            )
            scored = scored[: request.limit]
        except IntelligenceError as exc:
            return self._failed(
                kind=IntelligenceTraceKind.COMMUNICATION_RETRIEVE,
                started_at=started_at,
                t0=t0,
                error=exc,
                correlation_id=request.correlation_id,
                request_id=request.request_id,
                tenant_id=resolution.tenant_id,
                tenant_authority_source=resolution.source.value,
            )
        except Exception as exc:  # noqa: BLE001
            _logger.exception(
                "retrieve_patterns failed; folding onto envelope"
            )
            return self._failed(
                kind=IntelligenceTraceKind.COMMUNICATION_RETRIEVE,
                started_at=started_at,
                t0=t0,
                error=exc,
                correlation_id=request.correlation_id,
                request_id=request.request_id,
                tenant_id=resolution.tenant_id,
                tenant_authority_source=resolution.source.value,
            )

        ended_at = datetime.now(tz=timezone.utc)
        latency = (time.perf_counter() - t0) * 1000.0
        sequence = self._next_sequence()
        result = RetrieveCommunicationPatternsResult(
            sequence=sequence,
            runtime_instance_id=self._runtime_instance_id,
            started_at=started_at,
            ended_at=ended_at,
            latency_ms=latency,
            correlation_id=request.correlation_id,
            request_id=request.request_id,
            candidates=tuple(scored),
        )
        return IntelligenceEnvelope(
            trace=self._trace(
                kind=IntelligenceTraceKind.COMMUNICATION_RETRIEVE,
                started_at=started_at,
                ended_at=ended_at,
                latency=latency,
                sequence=sequence,
                correlation_id=request.correlation_id,
                request_id=request.request_id,
                tenant_id=resolution.tenant_id,
                tenant_authority_source=resolution.source.value,
            ),
            result=result,
        )

    # ─── helpers ────────────────────────────────────────────────────

    def _next_sequence(self) -> int:
        self._sequence += 1
        return self._sequence

    def _trace(  # noqa: PLR0913
        self,
        *,
        kind: IntelligenceTraceKind,
        started_at: datetime,
        ended_at: datetime,
        latency: float,
        sequence: int,
        correlation_id: str | None,
        request_id: str | None,
        tenant_id: str | None,
        error: str | None = None,
        tenant_authority_source: str | None = None,
    ) -> IntelligenceTrace:
        return IntelligenceTrace(
            trace_id=generate_trace_id(),
            kind=kind,
            runtime_instance_id=self._runtime_instance_id,
            sequence=sequence,
            started_at=started_at,
            ended_at=ended_at,
            latency_ms=latency,
            correlation_id=correlation_id,
            request_id=request_id,
            tenant_id=tenant_id,
            error=error,
            tenant_authority_source=tenant_authority_source,
        )

    def _failed(  # noqa: PLR0913
        self,
        *,
        kind: IntelligenceTraceKind,
        started_at: datetime,
        t0: float,
        error: BaseException,
        correlation_id: str | None,
        request_id: str | None,
        tenant_id: str | None,
        tenant_authority_source: str | None = None,
    ) -> IntelligenceEnvelope:
        ended_at = datetime.now(tz=timezone.utc)
        latency = (time.perf_counter() - t0) * 1000.0
        return IntelligenceEnvelope(
            trace=self._trace(
                kind=kind,
                started_at=started_at,
                ended_at=ended_at,
                latency=latency,
                sequence=self._sequence,
                correlation_id=correlation_id,
                request_id=request_id,
                tenant_id=tenant_id,
                error=f"{error.__class__.__name__}: {error}",
                tenant_authority_source=tenant_authority_source,
            ),
            result=None,
            error=error,
        )


__all__ = ["CommunicationRuntime"]
