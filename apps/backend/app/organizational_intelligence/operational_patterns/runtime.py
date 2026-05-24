"""`OperationalPatternAnalysisRuntime` — analysis only, never correction.

The runtime accepts a batch of caller-supplied observations and
returns an immutable `OperationalPatternAnalysis` wrapped in an
`IntelligenceEnvelope`. It is **pure analysis**: it does not
persist, mutate, route, or schedule. It NEVER:

* contacts sibling substrates,
* mutates any state outside its own runtime-instance sequence
  counter (which is internal to envelope chronology only),
* generates recommendations (that is `RecommendationRuntime`),
* schedules retraining or remediation,
* persists the analysis (callers own persistence).
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone

from app.organizational_intelligence.contracts.requests import (
    AnalyzeOperationalPatternsRequest,
)
from app.organizational_intelligence.contracts.results import (
    AnalyzeOperationalPatternsResult,
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
    derive_operational_pattern_analysis_id,
    generate_trace_id,
)
from app.organizational_intelligence.models.pattern import (
    OperationalPatternAnalysis,
)
from app.organizational_intelligence.serializers.canonical import (
    canonicalize_attributes,
)
from app.organizational_intelligence.traces.trace import (
    IntelligenceTrace,
)

_logger = logging.getLogger(__name__)

_ANALYZER_SIGNATURE = "deterministic.operational_pattern.v1"


class OperationalPatternAnalysisRuntime:
    """Pure deterministic operational-pattern analysis runtime."""

    __slots__ = (
        "_runtime_instance_id",
        "_sequence",
    )

    def __init__(self) -> None:
        self._runtime_instance_id = uuid.uuid4()  # EPHEMERAL: runtime trace only
        self._sequence = 0

    @property
    def runtime_instance_id(self) -> uuid.UUID:
        return self._runtime_instance_id

    async def analyze(
        self, request: AnalyzeOperationalPatternsRequest
    ) -> IntelligenceEnvelope:
        started_at = datetime.now(tz=timezone.utc)
        t0 = time.perf_counter()
        try:
            if not request.seed:
                raise IntelligenceValidationError(
                    "analyze.seed must be non-empty"
                )
            if not request.observations:
                raise IntelligenceValidationError(
                    "analyze.observations must be non-empty"
                )
            sorted_observations = tuple(
                sorted(
                    request.observations,
                    key=lambda o: (
                        o.kind.value,
                        -o.occurrence_count,
                        o.first_seen_at,
                        str(o.observation_id),
                    ),
                )
            )
            summary_parts = [
                f"{o.kind.value}={o.occurrence_count}"
                for o in sorted_observations
            ]
            analysis = OperationalPatternAnalysis(
                analysis_id=(
                    derive_operational_pattern_analysis_id(
                        seed=request.seed
                    )
                ),
                seed=request.seed,
                analyzed_at=started_at,
                analyzer_signature=_ANALYZER_SIGNATURE,
                observations=sorted_observations,
                summary=" | ".join(sorted(summary_parts)),
                metadata=canonicalize_attributes(
                    request.metadata
                ),
            )
        except IntelligenceError as exc:
            return self._failed(
                started_at=started_at,
                t0=t0,
                error=exc,
                correlation_id=request.correlation_id,
                request_id=request.request_id,
            )
        except Exception as exc:  # noqa: BLE001
            _logger.exception(
                "operational pattern analyze failed; folding onto envelope"
            )
            return self._failed(
                started_at=started_at,
                t0=t0,
                error=exc,
                correlation_id=request.correlation_id,
                request_id=request.request_id,
            )

        ended_at = datetime.now(tz=timezone.utc)
        latency = (time.perf_counter() - t0) * 1000.0
        sequence = self._next_sequence()
        result = AnalyzeOperationalPatternsResult(
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
                kind=IntelligenceTraceKind.PATTERN_ANALYZE,
                runtime_instance_id=self._runtime_instance_id,
                sequence=sequence,
                started_at=started_at,
                ended_at=ended_at,
                latency_ms=latency,
                correlation_id=request.correlation_id,
                request_id=request.request_id,
            ),
            result=result,
        )

    def _next_sequence(self) -> int:
        self._sequence += 1
        return self._sequence

    def _failed(
        self,
        *,
        started_at: datetime,
        t0: float,
        error: BaseException,
        correlation_id: str | None,
        request_id: str | None,
    ) -> IntelligenceEnvelope:
        # Chronology integrity (Core Law 3): failure envelopes consume
        # a fresh monotonic sequence; reusing `self._sequence` without
        # incrementing collides on consecutive failures.
        ended_at = datetime.now(tz=timezone.utc)
        latency = (time.perf_counter() - t0) * 1000.0
        sequence = self._next_sequence()
        return IntelligenceEnvelope(
            trace=IntelligenceTrace(
                trace_id=generate_trace_id(),
                kind=IntelligenceTraceKind.PATTERN_ANALYZE,
                runtime_instance_id=self._runtime_instance_id,
                sequence=sequence,
                started_at=started_at,
                ended_at=ended_at,
                latency_ms=latency,
                correlation_id=correlation_id,
                request_id=request_id,
                error=f"{error.__class__.__name__}: {error}",
            ),
            result=None,
            error=error,
        )


__all__ = ["OperationalPatternAnalysisRuntime"]
