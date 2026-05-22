"""Dispatch-path arbitration facade.

This runtime adapter wires the existing arbitration substrate into the
live dispatch service without granting arbitration executive authority.
It translates coordination/governance/proposal facts into an
``ArbitrationCase``, asks ``OperationalArbitrationRuntime`` to evaluate
that case, and projects the persisted evaluation through the existing
Phase 2-I arbitration bridge.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping, Protocol, Sequence

from app.arbitration.contracts import ArbitrationRequest
from app.arbitration.envelopes import ArbitrationEnvelope
from app.arbitration.enums import (
    ArbitrationAuthorityLevel,
    ArbitrationOutcome,
    ArbitrationVerdictKind,
)
from app.arbitration.identity import (
    ArbitrationEvaluationId,
    derive_case_id,
    derive_evaluation_id,
    derive_recommendation_id,
    derive_signal_id,
)
from app.arbitration.models import (
    ArbitrationCase,
    ArbitrationRecommendation,
    ArbitrationSignal,
)
from app.arbitration.models.case import DEFAULT_MAX_ITERATIONS
from app.arbitration.runtime import OperationalArbitrationRuntime
from app.coordination.contracts.results import (
    CoordinationDispatchOutcome,
    CoordinationDispatchResult,
)
from app.identity import AuthorityContext


class _DispatchArbitrationProjector(Protocol):
    async def project_evaluation(
        self,
        evaluation_id: ArbitrationEvaluationId | str,
        *,
        expected_tenant_id: str | None = None,
    ) -> object:
        ...


def _empty_metadata() -> Mapping[str, Any]:
    return {}


@dataclass(frozen=True, slots=True)
class DispatchArbitrationProposal:
    """One advisory proposal entering the live dispatch path."""

    proposer_id: str
    directive: str
    verdict: ArbitrationVerdictKind = ArbitrationVerdictKind.ALLOW
    authority: ArbitrationAuthorityLevel = ArbitrationAuthorityLevel.ARBITRATION
    reason: str = ""
    emitted_at: datetime | None = None
    metadata: Mapping[str, Any] = field(default_factory=_empty_metadata)


@dataclass(frozen=True, slots=True)
class DispatchArbitrationEvaluation:
    """Result of one dispatch-path arbitration evaluation."""

    envelope: ArbitrationEnvelope
    projection: object | None
    should_halt: bool
    halt_reason: str | None = None

    @property
    def evaluation_id(self) -> str | None:
        if self.envelope.result is None:
            return None
        return str(self.envelope.result.evaluation_id)

    @property
    def outcome(self) -> str | None:
        if self.envelope.result is None:
            return None
        return self.envelope.result.outcome.value


class DispatchArbitrationRuntime:
    """Runtime facade for dispatch-path arbitration and projection."""

    __slots__ = ("_arbitration_runtime", "_projector")

    def __init__(
        self,
        *,
        arbitration_runtime: OperationalArbitrationRuntime,
        projector: _DispatchArbitrationProjector,
    ) -> None:
        self._arbitration_runtime = arbitration_runtime
        self._projector = projector

    async def evaluate(
        self,
        *,
        coordination_result: CoordinationDispatchResult,
        proposals: Sequence[DispatchArbitrationProposal],
        tenant_id: str,
        authority: AuthorityContext,
        correlation_id: str | None,
        request_id: str | None,
        metadata: Mapping[str, Any] | None = None,
    ) -> DispatchArbitrationEvaluation:
        """Evaluate dispatch proposals and project the persisted record.

        The facade performs exactly one arbitration evaluation. When
        multiple proposals compete, the case is marked as already at
        the dispatch-path iteration bound; the existing deadlock
        evaluator then emits a ``DeadlockWitness`` and arbitration
        returns ``ARBITRATION_DEADLOCK``. No re-arbitration loop is
        attempted.
        """

        proposal_tuple = tuple(proposals)
        case_seed = _case_seed(
            coordination_result=coordination_result,
            tenant_id=tenant_id,
            proposals=proposal_tuple,
        )
        case = _build_case(
            coordination_result=coordination_result,
            proposals=proposal_tuple,
            tenant_id=tenant_id,
            seed=case_seed,
            metadata=metadata or {},
        )
        envelope = await self._arbitration_runtime.evaluate(
            ArbitrationRequest(
                case=case,
                correlation_id=correlation_id,
                request_id=request_id,
                tenant_id=tenant_id,
                authority=authority,
                evaluation_id_override=derive_evaluation_id(
                    seed=f"{case_seed}:evaluation"
                ),
                metadata={
                    "arbitration.dispatch.coordination_id": str(
                        coordination_result.coordination_id
                    ),
                    "arbitration.dispatch.proposal_count": len(
                        proposal_tuple
                    ),
                    "arbitration.dispatch.competing_proposals": (
                        _has_competing_proposals(proposal_tuple)
                    ),
                    **dict(metadata or {}),
                },
            )
        )
        result = envelope.result
        projection: object | None = None
        if result is not None:
            projection = await self._projector.project_evaluation(
                result.evaluation_id,
                expected_tenant_id=tenant_id,
            )
        should_halt = (
            result is not None
            and result.outcome is ArbitrationOutcome.ARBITRATION_DEADLOCK
        )
        return DispatchArbitrationEvaluation(
            envelope=envelope,
            projection=projection,
            should_halt=should_halt,
            halt_reason=result.reason if should_halt and result else None,
        )


def _build_case(
    *,
    coordination_result: CoordinationDispatchResult,
    proposals: tuple[DispatchArbitrationProposal, ...],
    tenant_id: str,
    seed: str,
    metadata: Mapping[str, Any],
) -> ArbitrationCase:
    competing = _has_competing_proposals(proposals)
    signals = [_governance_signal(coordination_result, seed=seed)]
    signals.extend(
        _proposal_signal(proposal, seed=seed, ordinal=ordinal)
        for ordinal, proposal in enumerate(proposals)
    )
    recommendations = tuple(
        _proposal_recommendation(proposal, seed=seed, ordinal=ordinal)
        for ordinal, proposal in enumerate(proposals)
    )
    return ArbitrationCase(
        case_id=derive_case_id(seed=seed),
        signals=tuple(signals),
        recommendations=recommendations,
        iteration_count=(
            DEFAULT_MAX_ITERATIONS if competing else 1
        ),
        max_iterations=DEFAULT_MAX_ITERATIONS,
        subject=f"coordination.dispatch:{coordination_result.coordination_id}",
        tenant_id=tenant_id,
        metadata={
            "arbitration.dispatch.coordination_id": str(
                coordination_result.coordination_id
            ),
            "arbitration.dispatch.competing_proposals": competing,
            **dict(metadata),
        },
    )


def _governance_signal(
    result: CoordinationDispatchResult,
    *,
    seed: str,
) -> ArbitrationSignal:
    source_id = (
        str(result.trace.governance_decision_id)
        if result.trace.governance_decision_id is not None
        else str(result.coordination_id)
    )
    return ArbitrationSignal(
        signal_id=derive_signal_id(seed=f"{seed}:governance:{source_id}"),
        authority=ArbitrationAuthorityLevel.GOVERNANCE,
        verdict=_verdict_from_coordination(result.outcome),
        source_substrate="governance",
        source_id=source_id,
        reason=result.error or result.trace.error or result.outcome.value,
        emitted_at=result.trace.ended_at,
        metadata={
            "coordination.dispatch_id": str(result.coordination_id),
            "coordination.outcome": result.outcome.value,
            "governance.decision_id": source_id,
        },
    )


def _proposal_signal(
    proposal: DispatchArbitrationProposal,
    *,
    seed: str,
    ordinal: int,
) -> ArbitrationSignal:
    return ArbitrationSignal(
        signal_id=derive_signal_id(
            seed=f"{seed}:proposal-signal:{ordinal}:{proposal.proposer_id}"
        ),
        authority=proposal.authority,
        verdict=proposal.verdict,
        source_substrate="dispatch.proposal",
        source_id=proposal.proposer_id,
        reason=proposal.reason,
        emitted_at=proposal.emitted_at,
        metadata={
            "arbitration.dispatch.directive": proposal.directive,
            **dict(proposal.metadata),
        },
    )


def _proposal_recommendation(
    proposal: DispatchArbitrationProposal,
    *,
    seed: str,
    ordinal: int,
) -> ArbitrationRecommendation:
    return ArbitrationRecommendation(
        recommendation_id=derive_recommendation_id(
            seed=f"{seed}:proposal-recommendation:{ordinal}:{proposal.proposer_id}"
        ),
        authority=proposal.authority,
        directive=proposal.directive,
        source_substrate="dispatch.proposal",
        source_id=proposal.proposer_id,
        reason=proposal.reason,
        emitted_at=proposal.emitted_at,
        metadata=dict(proposal.metadata),
    )


def _verdict_from_coordination(
    outcome: CoordinationDispatchOutcome,
) -> ArbitrationVerdictKind:
    if outcome is CoordinationDispatchOutcome.ACCEPTED:
        return ArbitrationVerdictKind.ALLOW
    if outcome is CoordinationDispatchOutcome.DEGRADED:
        return ArbitrationVerdictKind.DEGRADE
    if outcome in {
        CoordinationDispatchOutcome.DENIED,
        CoordinationDispatchOutcome.POLICY_DENIED,
        CoordinationDispatchOutcome.TOPOLOGY_DENIED,
        CoordinationDispatchOutcome.TOPOLOGY_BOUNDARY_VIOLATION,
        CoordinationDispatchOutcome.TOPOLOGY_DEPTH_EXCEEDED,
    }:
        return ArbitrationVerdictKind.DENY
    if outcome in {
        CoordinationDispatchOutcome.POLICY_ESCALATED,
        CoordinationDispatchOutcome.TOPOLOGY_ESCALATED,
    }:
        return ArbitrationVerdictKind.ESCALATE
    return ArbitrationVerdictKind.UNKNOWN


def _has_competing_proposals(
    proposals: tuple[DispatchArbitrationProposal, ...],
) -> bool:
    if len(proposals) < 2:
        return False
    signatures = {
        (proposal.authority, proposal.verdict, proposal.directive)
        for proposal in proposals
    }
    return len(signatures) > 1


def _case_seed(
    *,
    coordination_result: CoordinationDispatchResult,
    tenant_id: str,
    proposals: tuple[DispatchArbitrationProposal, ...],
) -> str:
    proposal_signature = "|".join(
        (
            f"{idx}:{proposal.proposer_id}:"
            f"{proposal.authority.value}:"
            f"{proposal.verdict.value}:{proposal.directive}"
        )
        for idx, proposal in enumerate(proposals)
    )
    return (
        "dispatch-arbitration:v1:"
        f"{tenant_id}:{coordination_result.coordination_id}:"
        f"{coordination_result.outcome.value}:{proposal_signature}"
    )


__all__ = [
    "DispatchArbitrationEvaluation",
    "DispatchArbitrationProposal",
    "DispatchArbitrationRuntime",
]
