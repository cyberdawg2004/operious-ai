"""`MemoryEvolutionRuntime` — the central discipline of Sprint O.

Responsibilities ONLY:

* `propose()`     — build a candidate + proposal + UNDER_REVIEW
                     memory artifact. NO auto-promotion.
* `approve()`     — record an `ApprovalRecord` and lift the
                     candidate's artifact to APPROVED + ELIGIBLE.
                     Refuses unless the approval is from a human
                     authority and targets the candidate.
* `reject()`      — record an `ApprovalRecord` and mark the
                     candidate's artifact REJECTED + INELIGIBLE.
* `supersede()`   — replace an APPROVED artifact with a newer
                     APPROVED artifact, preserving lineage.
                     Requires explicit approval.
* `retire()`      — explicit retirement; requires approval.
* `list()`        — read-only listing.

What this runtime MUST NEVER do:

* learn during execution,
* mutate operational state externally,
* invoke an LLM,
* auto-promote / auto-route / auto-execute,
* schedule retraining,
* contact sibling-substrate runtimes.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import replace as _dc_replace
from datetime import datetime, timezone

from app.organizational_intelligence.contracts.requests import (
    ApprovePatternRequest,
    ListMemoryArtifactsRequest,
    MemoryEvolutionProposalRequest,
    RejectPatternRequest,
    RetireMemoryArtifactRequest,
    SupersedeMemoryArtifactRequest,
)
from app.organizational_intelligence.contracts.results import (
    ApprovePatternResult,
    ListMemoryArtifactsResult,
    MemoryEvolutionProposalResult,
    RejectPatternResult,
    RetireMemoryArtifactResult,
    SupersedeMemoryArtifactResult,
)
from app.organizational_intelligence.envelopes import (
    IntelligenceEnvelope,
)
from app.organizational_intelligence.enums import (
    ApprovalDecision,
    IntelligenceTraceKind,
    MemoryArtifactStatus,
    RetrievalEligibility,
)
from app.organizational_intelligence.exceptions import (
    IntelligenceApprovalError,
    IntelligenceAuthorityError,
    IntelligenceError,
    IntelligenceLineageError,
    IntelligenceNotFoundError,
    IntelligenceValidationError,
)
from app.organizational_intelligence.governance.approval_gate import (
    require_approval_for_promotion,
    require_approval_for_supersession,
)
from app.organizational_intelligence.identity import (
    CandidatePatternId,
    MemoryArtifactId,
    derive_approved_pattern_id,
    derive_memory_artifact_id,
    derive_memory_evolution_proposal_id,
    generate_trace_id,
)
from app.organizational_intelligence.lineage.tracker import (
    build_lineage_for_root,
    build_lineage_for_successor,
)
from app.organizational_intelligence.models.memory import (
    ApprovedPattern,
    MemoryEvolutionProposal,
    OrganizationalMemoryArtifact,
)
from app.organizational_intelligence.persistence.queries import (
    MemoryArtifactQuery,
)
from app.organizational_intelligence.persistence.repository import (
    IntelligencePersistenceProtocol,
)
from app.organizational_intelligence.retrieval.eligibility import (
    derive_eligibility,
)
from app.organizational_intelligence.serializers.canonical import (
    canonicalize_attributes,
)
from app.organizational_intelligence.traces.trace import (
    IntelligenceTrace,
)
from app.organizational_intelligence.training.extractor import (
    DeterministicCandidateExtractor,
)

_logger = logging.getLogger(__name__)

_CANDIDATE_TARGET_KIND = "candidate_pattern"
_ARTIFACT_TARGET_KIND = "memory_artifact"


class MemoryEvolutionRuntime:
    """Governed memory-evolution pipeline."""

    __slots__ = (
        "_persistence",
        "_extractor",
        "_runtime_instance_id",
        "_sequence",
    )

    def __init__(
        self,
        *,
        persistence: IntelligencePersistenceProtocol,
        extractor: DeterministicCandidateExtractor | None = None,
    ) -> None:
        if persistence is None:
            raise IntelligenceValidationError(
                "MemoryEvolutionRuntime requires a persistence backend"
            )
        self._persistence = persistence
        self._extractor = (
            extractor or DeterministicCandidateExtractor()
        )
        self._runtime_instance_id = uuid.uuid4()
        self._sequence = 0

    @property
    def runtime_instance_id(self) -> uuid.UUID:
        return self._runtime_instance_id

    # ─── propose ────────────────────────────────────────────────────

    async def propose(
        self, request: MemoryEvolutionProposalRequest
    ) -> IntelligenceEnvelope:
        started_at = datetime.now(tz=timezone.utc)
        t0 = time.perf_counter()
        try:
            if not request.summary:
                raise IntelligenceValidationError(
                    "propose.summary must be non-empty"
                )
            if not request.body:
                raise IntelligenceValidationError(
                    "propose.body must be non-empty"
                )
            candidate = self._extractor.extract(
                observation_seed=request.observation_seed,
                summary=request.summary,
                body=request.body,
                kind=request.kind,
                evidence=request.evidence,
                extracted_at=started_at,
                scope=request.scope,
                tenant_id=request.tenant_id,
                attributes=request.metadata,
            )
            proposal = MemoryEvolutionProposal(
                proposal_id=derive_memory_evolution_proposal_id(
                    candidate_id=candidate.candidate_id
                ),
                candidate_id=candidate.candidate_id,
                proposed_at=started_at,
                rationale=(
                    request.rationale
                    or f"Candidate pattern proposed for human review "
                    f"(kind={request.kind.value})."
                ),
                evidence_summary=tuple(
                    sorted(set(request.evidence))
                ),
                status=MemoryArtifactStatus.CANDIDATE,
                metadata=canonicalize_attributes(
                    request.metadata
                ),
            )
            artifact_id = derive_memory_artifact_id(
                kind=request.kind.value,
                content_fingerprint=candidate.content_fingerprint,
            )
            existing = await self._persistence.get_memory_artifact(
                artifact_id
            )
            if existing is not None:
                # Idempotent re-proposal of the same content.
                artifact = existing
            else:
                lineage = build_lineage_for_root(
                    artifact_id=artifact_id
                )
                artifact = OrganizationalMemoryArtifact(
                    artifact_id=artifact_id,
                    kind=request.kind,
                    scope=request.scope,
                    tenant_id=request.tenant_id,
                    status=MemoryArtifactStatus.UNDER_REVIEW,
                    body=request.body,
                    content_fingerprint=(
                        candidate.content_fingerprint
                    ),
                    candidate_id=candidate.candidate_id,
                    approved_pattern_id=None,
                    approval_id=None,
                    proposal_id=proposal.proposal_id,
                    lineage=lineage,
                    eligibility=derive_eligibility(
                        MemoryArtifactStatus.UNDER_REVIEW
                    ),
                    created_at=started_at,
                    updated_at=started_at,
                    revision=1,
                )
                await self._persistence.save_candidate(candidate)
                await self._persistence.save_proposal(proposal)
                await self._persistence.save_memory_artifact(
                    artifact
                )
        except IntelligenceError as exc:
            return self._failed(
                kind=IntelligenceTraceKind.MEMORY_PROPOSE,
                started_at=started_at,
                t0=t0,
                error=exc,
                correlation_id=request.correlation_id,
                request_id=request.request_id,
                tenant_id=request.tenant_id,
            )
        except Exception as exc:  # noqa: BLE001
            _logger.exception(
                "propose failed; folding onto envelope"
            )
            return self._failed(
                kind=IntelligenceTraceKind.MEMORY_PROPOSE,
                started_at=started_at,
                t0=t0,
                error=exc,
                correlation_id=request.correlation_id,
                request_id=request.request_id,
                tenant_id=request.tenant_id,
            )

        ended_at = datetime.now(tz=timezone.utc)
        latency = (time.perf_counter() - t0) * 1000.0
        sequence = self._next_sequence()
        result = MemoryEvolutionProposalResult(
            sequence=sequence,
            runtime_instance_id=self._runtime_instance_id,
            started_at=started_at,
            ended_at=ended_at,
            latency_ms=latency,
            correlation_id=request.correlation_id,
            request_id=request.request_id,
            candidate=candidate,
            proposal=proposal,
            artifact=artifact,
        )
        return IntelligenceEnvelope(
            trace=self._trace(
                kind=IntelligenceTraceKind.MEMORY_PROPOSE,
                started_at=started_at,
                ended_at=ended_at,
                latency=latency,
                sequence=sequence,
                correlation_id=request.correlation_id,
                request_id=request.request_id,
                tenant_id=request.tenant_id,
            ),
            result=result,
        )

    # ─── approve ────────────────────────────────────────────────────

    async def approve(
        self, request: ApprovePatternRequest
    ) -> IntelligenceEnvelope:
        started_at = datetime.now(tz=timezone.utc)
        t0 = time.perf_counter()
        try:
            require_approval_for_promotion(
                approval=request.approval,
                target_id=request.candidate_id,
                target_kind=_CANDIDATE_TARGET_KIND,
            )
            candidate = await self._load_candidate(
                request.candidate_id
            )
            artifact = await self._load_artifact_for_candidate(
                candidate
            )
            if artifact.status is MemoryArtifactStatus.APPROVED:
                raise IntelligenceApprovalError(
                    "artifact already APPROVED; use supersede() to "
                    "replace it"
                )
            if artifact.status is MemoryArtifactStatus.REJECTED:
                raise IntelligenceApprovalError(
                    "rejected artifacts cannot be approved; create "
                    "a new proposal instead"
                )
            await self._persistence.save_approval(request.approval)
            approved_pattern = ApprovedPattern(
                approved_pattern_id=derive_approved_pattern_id(
                    candidate_id=candidate.candidate_id,
                    approval_id=request.approval.approval_id,
                ),
                candidate_id=candidate.candidate_id,
                approval_id=request.approval.approval_id,
                approved_at=started_at,
                body=candidate.body,
                kind=candidate.kind,
                scope=candidate.scope,
                tenant_id=candidate.tenant_id,
                approver_handle=request.approval.approver_handle,
            )
            updated_artifact = _dc_replace(
                artifact,
                status=MemoryArtifactStatus.APPROVED,
                approved_pattern_id=(
                    approved_pattern.approved_pattern_id
                ),
                approval_id=request.approval.approval_id,
                eligibility=RetrievalEligibility.ELIGIBLE,
                updated_at=started_at,
                revision=artifact.revision + 1,
            )
            await self._persistence.save_memory_artifact(
                updated_artifact
            )
        except IntelligenceError as exc:
            return self._failed(
                kind=IntelligenceTraceKind.MEMORY_APPROVE,
                started_at=started_at,
                t0=t0,
                error=exc,
                correlation_id=request.correlation_id,
                request_id=request.request_id,
            )
        except Exception as exc:  # noqa: BLE001
            _logger.exception(
                "approve failed; folding onto envelope"
            )
            return self._failed(
                kind=IntelligenceTraceKind.MEMORY_APPROVE,
                started_at=started_at,
                t0=t0,
                error=exc,
                correlation_id=request.correlation_id,
                request_id=request.request_id,
            )

        ended_at = datetime.now(tz=timezone.utc)
        latency = (time.perf_counter() - t0) * 1000.0
        sequence = self._next_sequence()
        result = ApprovePatternResult(
            sequence=sequence,
            runtime_instance_id=self._runtime_instance_id,
            started_at=started_at,
            ended_at=ended_at,
            latency_ms=latency,
            correlation_id=request.correlation_id,
            request_id=request.request_id,
            approved_pattern=approved_pattern,
            artifact=updated_artifact,
            approval=request.approval,
        )
        return IntelligenceEnvelope(
            trace=self._trace(
                kind=IntelligenceTraceKind.MEMORY_APPROVE,
                started_at=started_at,
                ended_at=ended_at,
                latency=latency,
                sequence=sequence,
                correlation_id=request.correlation_id,
                request_id=request.request_id,
                tenant_id=updated_artifact.tenant_id,
            ),
            result=result,
        )

    # ─── reject ─────────────────────────────────────────────────────

    async def reject(
        self, request: RejectPatternRequest
    ) -> IntelligenceEnvelope:
        started_at = datetime.now(tz=timezone.utc)
        t0 = time.perf_counter()
        try:
            if (
                request.approval.decision
                is not ApprovalDecision.REJECTED
            ):
                raise IntelligenceApprovalError(
                    "reject requires ApprovalDecision.REJECTED"
                )
            if request.approval.target_id != request.candidate_id:
                raise IntelligenceAuthorityError(
                    "approval target_id must match candidate_id"
                )
            if request.approval.target_kind != _CANDIDATE_TARGET_KIND:
                raise IntelligenceAuthorityError(
                    "approval target_kind must be candidate_pattern"
                )
            if request.approval.authority.value not in (
                "human_operator",
                "human_reviewer",
            ):
                raise IntelligenceAuthorityError(
                    "rejection requires a human authority"
                )
            candidate = await self._load_candidate(
                request.candidate_id
            )
            artifact = await self._load_artifact_for_candidate(
                candidate
            )
            if artifact.status is MemoryArtifactStatus.APPROVED:
                raise IntelligenceApprovalError(
                    "cannot reject an APPROVED artifact; use "
                    "retire() instead"
                )
            await self._persistence.save_approval(request.approval)
            updated_artifact = _dc_replace(
                artifact,
                status=MemoryArtifactStatus.REJECTED,
                approval_id=request.approval.approval_id,
                eligibility=RetrievalEligibility.INELIGIBLE,
                updated_at=started_at,
                revision=artifact.revision + 1,
            )
            await self._persistence.save_memory_artifact(
                updated_artifact
            )
        except IntelligenceError as exc:
            return self._failed(
                kind=IntelligenceTraceKind.MEMORY_REJECT,
                started_at=started_at,
                t0=t0,
                error=exc,
                correlation_id=request.correlation_id,
                request_id=request.request_id,
            )
        except Exception as exc:  # noqa: BLE001
            _logger.exception(
                "reject failed; folding onto envelope"
            )
            return self._failed(
                kind=IntelligenceTraceKind.MEMORY_REJECT,
                started_at=started_at,
                t0=t0,
                error=exc,
                correlation_id=request.correlation_id,
                request_id=request.request_id,
            )

        ended_at = datetime.now(tz=timezone.utc)
        latency = (time.perf_counter() - t0) * 1000.0
        sequence = self._next_sequence()
        result = RejectPatternResult(
            sequence=sequence,
            runtime_instance_id=self._runtime_instance_id,
            started_at=started_at,
            ended_at=ended_at,
            latency_ms=latency,
            correlation_id=request.correlation_id,
            request_id=request.request_id,
            artifact=updated_artifact,
            approval=request.approval,
        )
        return IntelligenceEnvelope(
            trace=self._trace(
                kind=IntelligenceTraceKind.MEMORY_REJECT,
                started_at=started_at,
                ended_at=ended_at,
                latency=latency,
                sequence=sequence,
                correlation_id=request.correlation_id,
                request_id=request.request_id,
                tenant_id=updated_artifact.tenant_id,
            ),
            result=result,
        )

    # ─── supersede ──────────────────────────────────────────────────

    async def supersede(
        self, request: SupersedeMemoryArtifactRequest
    ) -> IntelligenceEnvelope:
        started_at = datetime.now(tz=timezone.utc)
        t0 = time.perf_counter()
        try:
            if request.predecessor_id == request.successor_id:
                raise IntelligenceLineageError(
                    "predecessor and successor must differ"
                )
            require_approval_for_supersession(
                approval=request.approval,
                predecessor_id=request.predecessor_id,
                successor_id=request.successor_id,
                target_kind=_ARTIFACT_TARGET_KIND,
            )
            predecessor = await self._load_artifact(
                request.predecessor_id
            )
            successor = await self._load_artifact(
                request.successor_id
            )
            if predecessor.status is not MemoryArtifactStatus.APPROVED:
                raise IntelligenceApprovalError(
                    "predecessor must be APPROVED to be superseded"
                )
            if successor.status is not MemoryArtifactStatus.APPROVED:
                raise IntelligenceApprovalError(
                    "successor must be APPROVED to supersede"
                )
            await self._persistence.save_approval(request.approval)
            new_lineage = build_lineage_for_successor(
                artifact_id=successor.artifact_id,
                parent_lineage=predecessor.lineage,
            )
            updated_predecessor = _dc_replace(
                predecessor,
                status=MemoryArtifactStatus.SUPERSEDED,
                eligibility=RetrievalEligibility.INELIGIBLE,
                superseded_by=successor.artifact_id,
                updated_at=started_at,
                revision=predecessor.revision + 1,
            )
            updated_successor = _dc_replace(
                successor,
                lineage=new_lineage,
                updated_at=started_at,
                revision=successor.revision + 1,
            )
            await self._persistence.save_memory_artifact(
                updated_predecessor
            )
            await self._persistence.save_memory_artifact(
                updated_successor
            )
        except IntelligenceError as exc:
            return self._failed(
                kind=IntelligenceTraceKind.MEMORY_SUPERSEDE,
                started_at=started_at,
                t0=t0,
                error=exc,
                correlation_id=request.correlation_id,
                request_id=request.request_id,
            )
        except Exception as exc:  # noqa: BLE001
            _logger.exception(
                "supersede failed; folding onto envelope"
            )
            return self._failed(
                kind=IntelligenceTraceKind.MEMORY_SUPERSEDE,
                started_at=started_at,
                t0=t0,
                error=exc,
                correlation_id=request.correlation_id,
                request_id=request.request_id,
            )

        ended_at = datetime.now(tz=timezone.utc)
        latency = (time.perf_counter() - t0) * 1000.0
        sequence = self._next_sequence()
        result = SupersedeMemoryArtifactResult(
            sequence=sequence,
            runtime_instance_id=self._runtime_instance_id,
            started_at=started_at,
            ended_at=ended_at,
            latency_ms=latency,
            correlation_id=request.correlation_id,
            request_id=request.request_id,
            predecessor=updated_predecessor,
            successor=updated_successor,
            approval=request.approval,
        )
        return IntelligenceEnvelope(
            trace=self._trace(
                kind=IntelligenceTraceKind.MEMORY_SUPERSEDE,
                started_at=started_at,
                ended_at=ended_at,
                latency=latency,
                sequence=sequence,
                correlation_id=request.correlation_id,
                request_id=request.request_id,
                tenant_id=updated_successor.tenant_id,
            ),
            result=result,
        )

    # ─── retire ─────────────────────────────────────────────────────

    async def retire(
        self, request: RetireMemoryArtifactRequest
    ) -> IntelligenceEnvelope:
        started_at = datetime.now(tz=timezone.utc)
        t0 = time.perf_counter()
        try:
            require_approval_for_promotion(
                approval=request.approval,
                target_id=request.artifact_id,
                target_kind=_ARTIFACT_TARGET_KIND,
            )
            artifact = await self._load_artifact(
                request.artifact_id
            )
            if artifact.status is not MemoryArtifactStatus.APPROVED:
                raise IntelligenceApprovalError(
                    "only APPROVED artifacts may be retired"
                )
            await self._persistence.save_approval(request.approval)
            updated = _dc_replace(
                artifact,
                status=MemoryArtifactStatus.RETIRED,
                eligibility=RetrievalEligibility.RESTRICTED,
                approval_id=request.approval.approval_id,
                updated_at=started_at,
                revision=artifact.revision + 1,
            )
            await self._persistence.save_memory_artifact(updated)
        except IntelligenceError as exc:
            return self._failed(
                kind=IntelligenceTraceKind.MEMORY_RETIRE,
                started_at=started_at,
                t0=t0,
                error=exc,
                correlation_id=request.correlation_id,
                request_id=request.request_id,
            )
        except Exception as exc:  # noqa: BLE001
            _logger.exception(
                "retire failed; folding onto envelope"
            )
            return self._failed(
                kind=IntelligenceTraceKind.MEMORY_RETIRE,
                started_at=started_at,
                t0=t0,
                error=exc,
                correlation_id=request.correlation_id,
                request_id=request.request_id,
            )

        ended_at = datetime.now(tz=timezone.utc)
        latency = (time.perf_counter() - t0) * 1000.0
        sequence = self._next_sequence()
        result = RetireMemoryArtifactResult(
            sequence=sequence,
            runtime_instance_id=self._runtime_instance_id,
            started_at=started_at,
            ended_at=ended_at,
            latency_ms=latency,
            correlation_id=request.correlation_id,
            request_id=request.request_id,
            artifact=updated,
            approval=request.approval,
        )
        return IntelligenceEnvelope(
            trace=self._trace(
                kind=IntelligenceTraceKind.MEMORY_RETIRE,
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

    # ─── list ───────────────────────────────────────────────────────

    async def list_artifacts(
        self, request: ListMemoryArtifactsRequest
    ) -> IntelligenceEnvelope:
        started_at = datetime.now(tz=timezone.utc)
        t0 = time.perf_counter()
        try:
            query = MemoryArtifactQuery(
                tenant_id=request.tenant_id,
                kind=request.kind,
                eligibility=(
                    RetrievalEligibility.ELIGIBLE
                    if request.eligible_only
                    else None
                ),
                limit=request.limit,
                offset=request.offset,
            )
            page = await self._persistence.list_memory_artifacts(
                query
            )
        except Exception as exc:  # noqa: BLE001
            _logger.exception(
                "list_artifacts failed; folding onto envelope"
            )
            return self._failed(
                kind=IntelligenceTraceKind.MEMORY_LIST,
                started_at=started_at,
                t0=t0,
                error=exc,
                correlation_id=request.correlation_id,
                request_id=request.request_id,
                tenant_id=request.tenant_id,
            )

        ended_at = datetime.now(tz=timezone.utc)
        latency = (time.perf_counter() - t0) * 1000.0
        sequence = self._next_sequence()
        result = ListMemoryArtifactsResult(
            sequence=sequence,
            runtime_instance_id=self._runtime_instance_id,
            started_at=started_at,
            ended_at=ended_at,
            latency_ms=latency,
            correlation_id=request.correlation_id,
            request_id=request.request_id,
            artifacts=page.artifacts,
            total=page.total,
        )
        return IntelligenceEnvelope(
            trace=self._trace(
                kind=IntelligenceTraceKind.MEMORY_LIST,
                started_at=started_at,
                ended_at=ended_at,
                latency=latency,
                sequence=sequence,
                correlation_id=request.correlation_id,
                request_id=request.request_id,
                tenant_id=request.tenant_id,
            ),
            result=result,
        )

    # ─── helpers ────────────────────────────────────────────────────

    async def _load_candidate(
        self, candidate_id: CandidatePatternId
    ):
        candidate = await self._persistence.get_candidate(
            candidate_id
        )
        if candidate is None:
            raise IntelligenceNotFoundError(
                f"unknown candidate: {candidate_id}"
            )
        return candidate

    async def _load_artifact(
        self, artifact_id: MemoryArtifactId
    ) -> OrganizationalMemoryArtifact:
        artifact = await self._persistence.get_memory_artifact(
            artifact_id
        )
        if artifact is None:
            raise IntelligenceNotFoundError(
                f"unknown memory artifact: {artifact_id}"
            )
        return artifact

    async def _load_artifact_for_candidate(
        self, candidate
    ) -> OrganizationalMemoryArtifact:
        artifact_id = derive_memory_artifact_id(
            kind=candidate.kind.value,
            content_fingerprint=candidate.content_fingerprint,
        )
        return await self._load_artifact(artifact_id)

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
            ),
            result=None,
            error=error,
        )


__all__ = ["MemoryEvolutionRuntime"]
