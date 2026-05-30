"""`TonalityRuntime` — deterministic tonality classification.

Discipline:

* `classify()` produces a `TonalityAnalysis`. It does NOT
  recommend / inject / mutate anything. The analysis is metadata.
* The runtime never invents communication policy. Communication
  patterns are retrieved separately by `CommunicationRuntime`,
  and only APPROVED patterns participate.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone

from app.core.capability_gate import gate_or_deny
from app.governance.capability import (
    GovernanceRuntime,
    OperationalAct,
)
from app.identity import request_authority_resolution
from app.organizational_intelligence.contracts.requests import (
    ClassifyTonalityRequest,
)
from app.organizational_intelligence.contracts.results import (
    ClassifyTonalityResult,
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
from app.organizational_intelligence.identity import (
    derive_tonality_analysis_id,
    generate_trace_id,
)
from app.organizational_intelligence.models.tonality import (
    TonalityAnalysis,
)
from app.organizational_intelligence.persistence.repository import (
    IntelligencePersistenceProtocol,
)
from app.organizational_intelligence.serializers.canonical import (
    content_fingerprint,
)
from app.organizational_intelligence.tonality.classifier import (
    DeterministicTonalityClassifier,
)
from app.organizational_intelligence.traces.trace import (
    IntelligenceTrace,
)

_logger = logging.getLogger(__name__)


class TonalityRuntime:
    """Deterministic tonality-classification runtime."""

    __slots__ = (
        "_persistence",
        "_classifier",
        "_runtime_instance_id",
        "_sequence",
        "_capability_governance",
    )

    def __init__(
        self,
        *,
        persistence: IntelligencePersistenceProtocol,
        classifier: (
            DeterministicTonalityClassifier | None
        ) = None,
        capability_governance: GovernanceRuntime | None = None,
    ) -> None:
        self._persistence = persistence
        self._classifier = (
            classifier or DeterministicTonalityClassifier()
        )
        self._runtime_instance_id = uuid.uuid4()  # EPHEMERAL: runtime trace only
        self._sequence = 0
        # 2.75-\u03b1: capability legality gate. Inert when None.
        self._capability_governance = capability_governance

    @property
    def runtime_instance_id(self) -> uuid.UUID:
        return self._runtime_instance_id

    async def classify(
        self, request: ClassifyTonalityRequest
    ) -> IntelligenceEnvelope:
        started_at = datetime.now(tz=timezone.utc)
        t0 = time.perf_counter()
        # P2-A: singular authority resolution.
        resolution = request_authority_resolution(request)
        # 2.75-\u03b1: capability legality gate. Inert when None.
        denial = await gate_or_deny(
            self._capability_governance,
            act=OperationalAct.OI_TONALITY_CLASSIFY,
            authority=request.authority,
            resolution=resolution,
            actor="oi_tonality_runtime",
        )
        if denial is not None:
            return self._failed(
                started_at=started_at,
                t0=t0,
                error=denial,
                correlation_id=request.correlation_id,
                request_id=request.request_id,
                tenant_id=resolution.tenant_id,
                tenant_authority_source=resolution.source.value,
            )
        try:
            if not request.content:
                raise IntelligenceValidationError(
                    "classify.content must be non-empty"
                )
            fingerprint = content_fingerprint(request.content)
            tags = self._classifier.classify(
                content=request.content
            )
            primary = self._classifier.select_primary(tags)
            analysis = TonalityAnalysis(
                analysis_id=derive_tonality_analysis_id(
                    content_fingerprint=fingerprint,
                    correlation=request.correlation_hint,
                ),
                content_fingerprint=fingerprint,
                tags=tags,
                primary_tag=primary,
                analyzed_at=started_at,
                analyzer_signature=self._classifier.signature,
                correlation_hint=request.correlation_hint,
                tenant_id=resolution.tenant_id,
            )
            existing = await self._persistence.get_tonality_analysis(
                analysis.analysis_id
            )
            if existing is None:
                await self._persistence.save_tonality_analysis(
                    analysis
                )
            else:
                analysis = existing
        except IntelligenceError as exc:
            return self._failed(
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
                "tonality classify failed; folding onto envelope"
            )
            return self._failed(
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
        result = ClassifyTonalityResult(
            sequence=sequence,
            runtime_instance_id=self._runtime_instance_id,
            started_at=started_at,
            ended_at=ended_at,
            latency_ms=latency,
            correlation_id=request.correlation_id,
            request_id=request.request_id,
            analysis=analysis,
        )
        return IntelligenceEnvelope(
            trace=IntelligenceTrace(
                trace_id=generate_trace_id(),
                kind=IntelligenceTraceKind.TONALITY_CLASSIFY,
                runtime_instance_id=self._runtime_instance_id,
                sequence=sequence,
                started_at=started_at,
                ended_at=ended_at,
                latency_ms=latency,
                correlation_id=request.correlation_id,
                request_id=request.request_id,
                tenant_id=resolution.tenant_id,
                tenant_authority_source=resolution.source.value,
            ),
            result=result,
        )

    def _next_sequence(self) -> int:
        self._sequence += 1
        return self._sequence

    def _failed(  # noqa: PLR0913
        self,
        *,
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
            trace=IntelligenceTrace(
                trace_id=generate_trace_id(),
                kind=IntelligenceTraceKind.TONALITY_CLASSIFY,
                runtime_instance_id=self._runtime_instance_id,
                sequence=self._sequence,
                started_at=started_at,
                ended_at=ended_at,
                latency_ms=latency,
                correlation_id=correlation_id,
                request_id=request_id,
                tenant_id=tenant_id,
                error=f"{error.__class__.__name__}: {error}",
                tenant_authority_source=tenant_authority_source,
            ),
            result=None,
            error=error,
        )


__all__ = ["TonalityRuntime"]
