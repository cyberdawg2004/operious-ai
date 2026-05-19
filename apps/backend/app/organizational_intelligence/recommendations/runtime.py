"""`RecommendationRuntime` — generate + review recommendations.

Discipline:

* `generate()` produces a recommendation in PROPOSED status.
* `record_review()` accepts an `ApprovalRecord` (APPROVED /
  REJECTED / DEFERRED) and updates the recommendation. It does
  NOT auto-apply an APPROVED recommendation. Application is the
  caller's responsibility, with an explicit runtime call
  elsewhere.
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
from app.identity import project_optional_str
from app.identity import request_authority_resolution
from app.organizational_intelligence.contracts.requests import (
    ApproveRecommendationRequest,
    GenerateRecommendationRequest,
)
from app.organizational_intelligence.contracts.results import (
    ApproveRecommendationResult,
    GenerateRecommendationResult,
)
from app.organizational_intelligence.envelopes import (
    IntelligenceEnvelope,
)
from app.organizational_intelligence.enums import (
    ApprovalDecision,
    IntelligenceTraceKind,
    RecommendationStatus,
)
from app.organizational_intelligence.exceptions import (
    IntelligenceApprovalError,
    IntelligenceError,
    IntelligenceNotFoundError,
    IntelligenceValidationError,
)
from app.organizational_intelligence.approval_gates.approval_gate import (
    require_approval_for_review,
)
from app.organizational_intelligence.identity import (
    derive_recommendation_id,
    generate_trace_id,
)
from app.organizational_intelligence.models.recommendation import (
    OrganizationalRecommendation,
)
from app.organizational_intelligence.persistence.repository import (
    IntelligencePersistenceProtocol,
)
from app.organizational_intelligence.serializers.canonical import (
    canonicalize_attributes,
    content_fingerprint,
)
from app.organizational_intelligence.traces.trace import (
    IntelligenceTrace,
)

_logger = logging.getLogger(__name__)

_TARGET_KIND = "recommendation"


class RecommendationRuntime:
    """Inspectable recommendation generation + review runtime."""

    __slots__ = (
        "_persistence",
        "_runtime_instance_id",
        "_sequence",
        "_capability_governance",
    )

    def __init__(
        self,
        *,
        persistence: IntelligencePersistenceProtocol,
        capability_governance: GovernanceRuntime | None = None,
    ) -> None:
        self._persistence = persistence
        self._runtime_instance_id = uuid.uuid4()
        self._sequence = 0
        # 2.75-\u03b1: capability legality gate. Inert when None.
        self._capability_governance = capability_governance

    @property
    def runtime_instance_id(self) -> uuid.UUID:
        return self._runtime_instance_id

    # ─── generate ───────────────────────────────────────────────────

    async def generate(
        self, request: GenerateRecommendationRequest
    ) -> IntelligenceEnvelope:
        started_at = datetime.now(tz=timezone.utc)
        t0 = time.perf_counter()
        # P2-A: singular authority resolution.
        resolution = request_authority_resolution(request)
        # 2.75-\u03b1: capability legality gate. Inert when None.
        denial = await gate_or_deny(
            self._capability_governance,
            act=OperationalAct.OI_RECOMMENDATION_GENERATE,
            authority=request.authority,
            resolution=resolution,
            actor="oi_recommendations_runtime",
        )
        if denial is not None:
            return self._failed(
                kind=IntelligenceTraceKind.RECOMMENDATION_GENERATE,
                started_at=started_at,
                t0=t0,
                error=denial,
                correlation_id=request.correlation_id,
                request_id=request.request_id,
                tenant_id=resolution.tenant_id,
                tenant_authority_source=resolution.source.value,
            )
        try:
            if not request.title:
                raise IntelligenceValidationError(
                    "generate.title must be non-empty"
                )
            if not request.body:
                raise IntelligenceValidationError(
                    "generate.body must be non-empty"
                )
            seed_fp = content_fingerprint(
                {
                    "kind": request.kind.value,
                    "target": request.target_handle,
                    "title": request.title,
                    "body": request.body,
                    "rationale": request.rationale.summary,
                }
            )
            # ``project_optional_str`` disambiguates
            # ``tenant_id=None`` from ``tenant_id=""`` when composing
            # the recommendation's deterministic scope (Wedge B4
            # closure of audit CO-3 at the call-graph distance).
            rec_id = derive_recommendation_id(
                scope=(
                    f"{request.scope.value}|"
                    f"{project_optional_str(resolution.tenant_id)}"
                ),
                content_fingerprint=seed_fp,
            )
            existing = await self._persistence.get_recommendation(
                rec_id
            )
            if existing is not None:
                recommendation = existing
            else:
                recommendation = OrganizationalRecommendation(
                    recommendation_id=rec_id,
                    kind=request.kind,
                    scope=request.scope,
                    tenant_id=resolution.tenant_id,
                    status=RecommendationStatus.PROPOSED,
                    title=request.title,
                    body=request.body,
                    rationale=request.rationale,
                    target_handle=request.target_handle,
                    proposed_at=started_at,
                    revision=1,
                    metadata=canonicalize_attributes(
                        request.metadata
                    ),
                )
                await self._persistence.save_recommendation(
                    recommendation
                )
        except IntelligenceError as exc:
            return self._failed(
                kind=IntelligenceTraceKind.RECOMMENDATION_GENERATE,
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
                "recommendation generate failed; folding onto envelope"
            )
            return self._failed(
                kind=IntelligenceTraceKind.RECOMMENDATION_GENERATE,
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
        result = GenerateRecommendationResult(
            sequence=sequence,
            runtime_instance_id=self._runtime_instance_id,
            started_at=started_at,
            ended_at=ended_at,
            latency_ms=latency,
            correlation_id=request.correlation_id,
            request_id=request.request_id,
            recommendation=recommendation,
        )
        return IntelligenceEnvelope(
            trace=self._trace(
                kind=IntelligenceTraceKind.RECOMMENDATION_GENERATE,
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

    # ─── record_review ──────────────────────────────────────────────

    async def record_review(
        self, request: ApproveRecommendationRequest
    ) -> IntelligenceEnvelope:
        started_at = datetime.now(tz=timezone.utc)
        t0 = time.perf_counter()
        try:
            require_approval_for_review(
                approval=request.approval,
                target_id=request.recommendation_id,
                target_kind=_TARGET_KIND,
            )
            recommendation = (
                await self._persistence.get_recommendation(
                    request.recommendation_id
                )
            )
            if recommendation is None:
                raise IntelligenceNotFoundError(
                    "unknown recommendation: "
                    f"{request.recommendation_id}"
                )
            if recommendation.status not in (
                RecommendationStatus.PROPOSED,
                RecommendationStatus.REVIEWED,
                RecommendationStatus.DEFERRED,
            ):
                raise IntelligenceApprovalError(
                    f"recommendation status {recommendation.status.value} "
                    f"is terminal for review"
                )
            new_status = self._derive_status(
                approval_decision=request.approval.decision
            )
            await self._persistence.save_approval(request.approval)
            updated = _dc_replace(
                recommendation,
                status=new_status,
                approval_id=request.approval.approval_id,
                reviewed_at=started_at,
                revision=recommendation.revision + 1,
            )
            await self._persistence.save_recommendation(updated)
        except IntelligenceError as exc:
            return self._failed(
                kind=IntelligenceTraceKind.RECOMMENDATION_REVIEW,
                started_at=started_at,
                t0=t0,
                error=exc,
                correlation_id=request.correlation_id,
                request_id=request.request_id,
            )
        except Exception as exc:  # noqa: BLE001
            _logger.exception(
                "recommendation review failed; folding onto envelope"
            )
            return self._failed(
                kind=IntelligenceTraceKind.RECOMMENDATION_REVIEW,
                started_at=started_at,
                t0=t0,
                error=exc,
                correlation_id=request.correlation_id,
                request_id=request.request_id,
            )

        ended_at = datetime.now(tz=timezone.utc)
        latency = (time.perf_counter() - t0) * 1000.0
        sequence = self._next_sequence()
        result = ApproveRecommendationResult(
            sequence=sequence,
            runtime_instance_id=self._runtime_instance_id,
            started_at=started_at,
            ended_at=ended_at,
            latency_ms=latency,
            correlation_id=request.correlation_id,
            request_id=request.request_id,
            recommendation=updated,
            approval=request.approval,
        )
        return IntelligenceEnvelope(
            trace=self._trace(
                kind=IntelligenceTraceKind.RECOMMENDATION_REVIEW,
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

    @staticmethod
    def _derive_status(
        *, approval_decision: ApprovalDecision
    ) -> RecommendationStatus:
        if approval_decision is ApprovalDecision.APPROVED:
            return RecommendationStatus.APPROVED
        if approval_decision is ApprovalDecision.REJECTED:
            return RecommendationStatus.REJECTED
        return RecommendationStatus.DEFERRED

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


__all__ = ["RecommendationRuntime"]
