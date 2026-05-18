"""`SopRuntime` — SOP ingestion + analysis.

Discipline:

* `ingest_sop()` builds an immutable SOP record at status
  ``INGESTED`` (or ``DRAFT`` if the caller explicitly asked).
  It NEVER auto-runs analysis.
* `analyze_sop()` runs the deterministic analyzer and persists
  the analysis. It moves the SOP to ``ANALYZED``. It NEVER
  auto-runs ingestion or auto-applies findings.
* No method auto-promotes an SOP to APPROVED. Approval is an
  explicit flow handled by the recommendation runtime + human
  approval (which the runtime does NOT execute on its own).
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import replace as _dc_replace
from datetime import datetime, timezone

from app.governance.capability import (
    GovernanceRuntime,
    OperationalAct,
    gate_or_deny,
)
from app.identity import request_authority_resolution
from app.organizational_intelligence.contracts.requests import (
    AnalyzeSopRequest,
    IngestSopRequest,
)
from app.organizational_intelligence.contracts.results import (
    AnalyzeSopResult,
    IngestSopResult,
)
from app.organizational_intelligence.envelopes import (
    IntelligenceEnvelope,
)
from app.organizational_intelligence.enums import (
    IntelligenceTraceKind,
    SopStatus,
)
from app.organizational_intelligence.exceptions import (
    IntelligenceError,
    IntelligenceNotFoundError,
    IntelligenceValidationError,
)
from app.organizational_intelligence.identity import (
    SopId,
    derive_sop_analysis_id,
    derive_sop_id,
    derive_sop_version_id,
    generate_trace_id,
)
from app.organizational_intelligence.models.sop import (
    SopAnalysis,
    SopVersion,
    StandardOperatingProcedure,
)
from app.organizational_intelligence.persistence.repository import (
    IntelligencePersistenceProtocol,
)
from app.organizational_intelligence.serializers.canonical import (
    canonicalize_attributes,
    content_fingerprint,
)
from app.organizational_intelligence.sop.analyzer import (
    DeterministicSopAnalyzer,
)
from app.organizational_intelligence.traces.trace import (
    IntelligenceTrace,
)

_logger = logging.getLogger(__name__)


class SopRuntime:
    """SOP ingestion + analysis runtime."""

    __slots__ = (
        "_persistence",
        "_analyzer",
        "_runtime_instance_id",
        "_sequence",
        "_capability_governance",
    )

    def __init__(
        self,
        *,
        persistence: IntelligencePersistenceProtocol,
        analyzer: DeterministicSopAnalyzer | None = None,
        capability_governance: GovernanceRuntime | None = None,
    ) -> None:
        self._persistence = persistence
        self._analyzer = analyzer or DeterministicSopAnalyzer()
        self._runtime_instance_id = uuid.uuid4()
        self._sequence = 0
        # 2.75-\u03b1: capability legality gate. Inert when None.
        self._capability_governance = capability_governance

    @property
    def runtime_instance_id(self) -> uuid.UUID:
        return self._runtime_instance_id

    # ─── ingest_sop ─────────────────────────────────────────────────

    async def ingest_sop(
        self, request: IngestSopRequest
    ) -> IntelligenceEnvelope:
        started_at = datetime.now(tz=timezone.utc)
        t0 = time.perf_counter()
        # P2-A: singular authority resolution.
        resolution = request_authority_resolution(request)
        # 2.75-\u03b1: capability legality gate. Inert when None.
        denial = await gate_or_deny(
            self._capability_governance,
            act=OperationalAct.OI_SOP_INGEST,
            authority=request.authority,
            resolution=resolution,
            actor="oi_sop_runtime",
        )
        if denial is not None:
            return self._failed(
                kind=IntelligenceTraceKind.SOP_INGEST,
                started_at=started_at,
                t0=t0,
                error=denial,
                correlation_id=request.correlation_id,
                request_id=request.request_id,
                tenant_id=resolution.tenant_id,
                tenant_authority_source=resolution.source.value,
            )
        try:
            if not request.body:
                raise IntelligenceValidationError(
                    "ingest_sop.body must be non-empty"
                )
            if not request.title:
                raise IntelligenceValidationError(
                    "ingest_sop.title must be non-empty"
                )
            sop_id = derive_sop_id(
                tenant_id=resolution.tenant_id,
                external_handle=request.external_handle,
            )
            existing = await self._persistence.get_sop(sop_id)
            new_version_number = (
                existing.current_version.version + 1
                if existing is not None
                else 1
            )
            version = SopVersion(
                version_id=derive_sop_version_id(
                    sop_id=sop_id, version=new_version_number
                ),
                sop_id=sop_id,
                version=new_version_number,
                title=request.title,
                body=request.body,
                content_fingerprint=content_fingerprint(
                    request.body
                ),
                ingested_at=started_at,
                author_handle=request.author_handle,
                metadata=canonicalize_attributes(
                    request.metadata
                ),
            )
            history = (
                existing.version_history
                + (existing.current_version.version_id,)
                if existing is not None
                else ()
            )
            sop = StandardOperatingProcedure(
                sop_id=sop_id,
                tenant_id=resolution.tenant_id,
                scope=request.scope,
                external_handle=request.external_handle,
                status=SopStatus.INGESTED,
                current_version=version,
                ingested_at=(
                    existing.ingested_at
                    if existing is not None
                    else started_at
                ),
                last_updated_at=started_at,
                version_history=history,
                revision=(
                    existing.revision + 1
                    if existing is not None
                    else 1
                ),
                metadata=canonicalize_attributes(
                    request.metadata
                ),
            )
            await self._persistence.save_sop(sop)
        except IntelligenceError as exc:
            return self._failed(
                kind=IntelligenceTraceKind.SOP_INGEST,
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
                "ingest_sop failed; folding onto envelope"
            )
            return self._failed(
                kind=IntelligenceTraceKind.SOP_INGEST,
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
        result = IngestSopResult(
            sequence=sequence,
            runtime_instance_id=self._runtime_instance_id,
            started_at=started_at,
            ended_at=ended_at,
            latency_ms=latency,
            correlation_id=request.correlation_id,
            request_id=request.request_id,
            sop=sop,
            version=version,
        )
        return IntelligenceEnvelope(
            trace=self._trace(
                kind=IntelligenceTraceKind.SOP_INGEST,
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

    # ─── analyze_sop ────────────────────────────────────────────────

    async def analyze_sop(
        self, request: AnalyzeSopRequest
    ) -> IntelligenceEnvelope:
        started_at = datetime.now(tz=timezone.utc)
        t0 = time.perf_counter()
        try:
            sop = await self._load_sop(request.sop_id)
            findings = self._analyzer.analyze(
                sop_version=sop.current_version
            )
            analysis = SopAnalysis(
                analysis_id=derive_sop_analysis_id(
                    sop_id=sop.sop_id,
                    version=sop.current_version.version,
                ),
                sop_id=sop.sop_id,
                sop_version=sop.current_version.version,
                analyzer_signature=self._analyzer.signature,
                analyzed_at=started_at,
                findings=findings,
                summary=(
                    f"{len(findings)} finding(s) detected"
                    if findings
                    else "no findings detected"
                ),
            )
            await self._persistence.save_sop_analysis(analysis)
            new_status = (
                SopStatus.ANALYZED
                if sop.status
                in (
                    SopStatus.DRAFT,
                    SopStatus.INGESTED,
                    SopStatus.ANALYZED,
                )
                else sop.status
            )
            updated = _dc_replace(
                sop,
                status=new_status,
                last_updated_at=started_at,
                revision=sop.revision + 1,
            )
            await self._persistence.save_sop(updated)
        except IntelligenceError as exc:
            return self._failed(
                kind=IntelligenceTraceKind.SOP_ANALYZE,
                started_at=started_at,
                t0=t0,
                error=exc,
                correlation_id=request.correlation_id,
                request_id=request.request_id,
            )
        except Exception as exc:  # noqa: BLE001
            _logger.exception(
                "analyze_sop failed; folding onto envelope"
            )
            return self._failed(
                kind=IntelligenceTraceKind.SOP_ANALYZE,
                started_at=started_at,
                t0=t0,
                error=exc,
                correlation_id=request.correlation_id,
                request_id=request.request_id,
            )

        ended_at = datetime.now(tz=timezone.utc)
        latency = (time.perf_counter() - t0) * 1000.0
        sequence = self._next_sequence()
        result = AnalyzeSopResult(
            sequence=sequence,
            runtime_instance_id=self._runtime_instance_id,
            started_at=started_at,
            ended_at=ended_at,
            latency_ms=latency,
            correlation_id=request.correlation_id,
            request_id=request.request_id,
            sop=updated,
            analysis=analysis,
        )
        return IntelligenceEnvelope(
            trace=self._trace(
                kind=IntelligenceTraceKind.SOP_ANALYZE,
                started_at=started_at,
                ended_at=ended_at,
                latency=latency,
                sequence=sequence,
                correlation_id=request.correlation_id,
                request_id=request.request_id,
                tenant_id=updated.tenant_id,
            ),
            result=result,
        )

    # ─── helpers ────────────────────────────────────────────────────

    async def _load_sop(
        self, sop_id: SopId
    ) -> StandardOperatingProcedure:
        sop = await self._persistence.get_sop(sop_id)
        if sop is None:
            raise IntelligenceNotFoundError(
                f"unknown SOP: {sop_id}"
            )
        return sop

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
        tenant_id: str | None = None,
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
        tenant_id: str | None = None,
        tenant_authority_source: str | None = None,
    ) -> IntelligenceEnvelope:
        # Chronology integrity (Core Law 3): failure envelopes consume
        # a fresh monotonic sequence; reusing `self._sequence` without
        # incrementing collides on consecutive failures.
        ended_at = datetime.now(tz=timezone.utc)
        latency = (time.perf_counter() - t0) * 1000.0
        sequence = self._next_sequence()
        return IntelligenceEnvelope(
            trace=self._trace(
                kind=kind,
                started_at=started_at,
                ended_at=ended_at,
                latency=latency,
                sequence=sequence,
                correlation_id=correlation_id,
                request_id=request_id,
                tenant_id=tenant_id,
                error=f"{error.__class__.__name__}: {error}",
                tenant_authority_source=tenant_authority_source,
            ),
            result=None,
            error=error,
        )


__all__ = ["SopRuntime"]
