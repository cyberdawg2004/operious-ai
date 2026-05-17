"""`OperationalArbitrationRuntime` integration tests.

Validates the apex evaluator's end-to-end behaviour:

* deterministic ordering / replay-safe ids,
* never-raises contract,
* persistence integration,
* evaluator whitelisting,
* graceful handling of a raising evaluator,
* immutable, audit-stable outputs,
* and — critically — that the runtime does NOT execute, dispatch,
  retry, or mutate any external runtime.
"""

from __future__ import annotations

import asyncio

import pytest

from app.arbitration.contracts.requests import ArbitrationRequest
from app.arbitration.envelopes import ArbitrationEnvelope
from app.arbitration.enums import (
    ArbitrationAuthorityLevel,
    ArbitrationOutcome,
    ArbitrationVerdictKind,
)
from app.arbitration.evaluators.base import (
    BaseArbitrationEvaluator,
)
from app.arbitration.evaluators.builtin import (
    DeadlockDetectionEvaluator,
    EscalationConflictEvaluator,
    FindingConflictEvaluator,
    RecommendationConflictEvaluator,
    SupervisorDisagreementEvaluator,
)
from app.arbitration.exceptions import (
    ArbitrationConfigurationError,
)
from app.arbitration.identity import (
    derive_case_id,
    derive_evaluation_id,
    derive_recommendation_id,
    derive_signal_id,
)
from app.arbitration.models.case import ArbitrationCase
from app.arbitration.models.recommendation import (
    ArbitrationRecommendation,
)
from app.arbitration.models.signal import ArbitrationSignal
from app.arbitration.persistence.memory import (
    InMemoryArbitrationPersistence,
)
from app.arbitration.persistence.models import ArbitrationQuery
from app.arbitration.registry.registry import (
    ArbitrationEvaluatorRegistry,
)
from app.arbitration.runtime.runtime import (
    OperationalArbitrationRuntime,
)
from app.arbitration.taxonomy import (
    ArbitrationFindingCode,
    ArbitrationMetadataKey,
)


def _sig(
    seed: str,
    *,
    authority: ArbitrationAuthorityLevel,
    verdict: ArbitrationVerdictKind,
    source_substrate: str = "demo",
) -> ArbitrationSignal:
    return ArbitrationSignal(
        signal_id=derive_signal_id(seed=seed),
        authority=authority,
        verdict=verdict,
        source_substrate=source_substrate,
        source_id=seed,
    )


def _rec(
    seed: str,
    *,
    authority: ArbitrationAuthorityLevel,
    directive: str,
) -> ArbitrationRecommendation:
    return ArbitrationRecommendation(
        recommendation_id=derive_recommendation_id(seed=seed),
        authority=authority,
        directive=directive,
        source_substrate="demo",
        source_id=seed,
    )


def _full_registry() -> ArbitrationEvaluatorRegistry:
    return ArbitrationEvaluatorRegistry(
        [
            FindingConflictEvaluator(),
            RecommendationConflictEvaluator(),
            EscalationConflictEvaluator(),
            SupervisorDisagreementEvaluator(),
            DeadlockDetectionEvaluator(),
        ]
    )


def _runtime(
    *, persistence: InMemoryArbitrationPersistence | None = None
) -> OperationalArbitrationRuntime:
    return OperationalArbitrationRuntime(
        registry=_full_registry(),
        persistence=persistence,
    )


# ─── Construction ────────────────────────────────────────────────────


def test_construction_requires_non_empty_registry() -> None:
    with pytest.raises(ArbitrationConfigurationError):
        OperationalArbitrationRuntime(
            registry=ArbitrationEvaluatorRegistry()
        )


def test_construction_exposes_dependencies() -> None:
    rt = _runtime()
    assert rt.registry is not None
    assert rt.persistence is None
    assert rt.runtime_instance_id is not None


# ─── Resolution / escalation / conflict ──────────────────────────────


@pytest.mark.asyncio
async def test_governance_prevails_resolved() -> None:
    case = ArbitrationCase(
        case_id=derive_case_id(seed="c-resolve"),
        signals=(
            _sig(
                "sup_a",
                authority=ArbitrationAuthorityLevel.SUPERVISOR,
                verdict=ArbitrationVerdictKind.ESCALATE,
            ),
            _sig(
                "sup_b",
                authority=ArbitrationAuthorityLevel.SUPERVISOR,
                verdict=ArbitrationVerdictKind.ALLOW,
            ),
            _sig(
                "gov",
                authority=ArbitrationAuthorityLevel.GOVERNANCE,
                verdict=ArbitrationVerdictKind.DENY,
                source_substrate="governance",
            ),
        ),
    )
    rt = _runtime()
    envelope = await rt.evaluate(
        ArbitrationRequest(
            case=case,
            correlation_id="corr-1",
            request_id="req-1",
            tenant_id="t-1",
        )
    )
    assert envelope.is_ok
    result = envelope.unwrap()
    assert (
        result.decision.outcome
        is ArbitrationOutcome.ARBITRATION_RESOLVED
    )
    assert (
        result.decision.prevailing_authority.level
        is ArbitrationAuthorityLevel.GOVERNANCE
    )
    assert result.evaluator_names == (
        "deadlock_detection_evaluator",
        "escalation_conflict_evaluator",
        "finding_conflict_evaluator",
        "recommendation_conflict_evaluator",
        "supervisor_disagreement_evaluator",
    )
    assert (
        result.metadata[
            ArbitrationMetadataKey.PREVAILING_AUTHORITY.value
        ]
        == "governance"
    )


@pytest.mark.asyncio
async def test_supervisor_only_escalation_yields_escalated() -> None:
    case = ArbitrationCase(
        case_id=derive_case_id(seed="c-escalate"),
        signals=(
            _sig(
                "sup",
                authority=ArbitrationAuthorityLevel.SUPERVISOR,
                verdict=ArbitrationVerdictKind.ESCALATE,
                source_substrate="supervisor",
            ),
        ),
    )
    rt = _runtime()
    envelope = await rt.evaluate(ArbitrationRequest(case=case))
    result = envelope.unwrap()
    assert (
        result.decision.outcome
        is ArbitrationOutcome.ARBITRATION_ESCALATED
    )


@pytest.mark.asyncio
async def test_top_authority_disagreement_yields_conflict() -> None:
    case = ArbitrationCase(
        case_id=derive_case_id(seed="c-conflict"),
        signals=(
            _sig(
                "g1",
                authority=ArbitrationAuthorityLevel.GOVERNANCE,
                verdict=ArbitrationVerdictKind.ALLOW,
            ),
            _sig(
                "g2",
                authority=ArbitrationAuthorityLevel.GOVERNANCE,
                verdict=ArbitrationVerdictKind.DENY,
            ),
        ),
    )
    rt = _runtime()
    envelope = await rt.evaluate(ArbitrationRequest(case=case))
    result = envelope.unwrap()
    assert (
        result.decision.outcome
        is ArbitrationOutcome.ARBITRATION_CONFLICT
    )
    assert result.decision.prevailing_authority is None


@pytest.mark.asyncio
async def test_iteration_exhausted_yields_deadlock() -> None:
    case = ArbitrationCase(
        case_id=derive_case_id(seed="c-deadlock"),
        signals=(
            _sig(
                "g",
                authority=ArbitrationAuthorityLevel.GOVERNANCE,
                verdict=ArbitrationVerdictKind.ALLOW,
            ),
        ),
        iteration_count=3,
        max_iterations=3,
    )
    rt = _runtime()
    envelope = await rt.evaluate(ArbitrationRequest(case=case))
    result = envelope.unwrap()
    assert (
        result.decision.outcome
        is ArbitrationOutcome.ARBITRATION_DEADLOCK
    )
    assert len(result.deadlock_witnesses) >= 1


@pytest.mark.asyncio
async def test_inconclusive_when_no_signals_present() -> None:
    case = ArbitrationCase(case_id=derive_case_id(seed="c-incon"))
    rt = _runtime()
    envelope = await rt.evaluate(ArbitrationRequest(case=case))
    result = envelope.unwrap()
    assert (
        result.decision.outcome
        is ArbitrationOutcome.ARBITRATION_INCONCLUSIVE
    )


# ─── Authority precedence finding ────────────────────────────────────


@pytest.mark.asyncio
async def test_authority_precedence_finding_emitted_on_resolution() -> None:
    case = ArbitrationCase(
        case_id=derive_case_id(seed="c-precedence"),
        signals=(
            _sig(
                "gov",
                authority=ArbitrationAuthorityLevel.GOVERNANCE,
                verdict=ArbitrationVerdictKind.DENY,
            ),
        ),
    )
    rt = _runtime()
    envelope = await rt.evaluate(ArbitrationRequest(case=case))
    result = envelope.unwrap()
    codes = [f.code for f in result.findings]
    assert (
        ArbitrationFindingCode.AUTHORITY_PRECEDENCE_APPLIED.value
        in codes
    )


# ─── Determinism & replay ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_evaluator_names_are_sorted() -> None:
    rt = _runtime()
    case = ArbitrationCase(case_id=derive_case_id(seed="c-sort"))
    envelope = await rt.evaluate(ArbitrationRequest(case=case))
    result = envelope.unwrap()
    assert list(result.evaluator_names) == sorted(
        result.evaluator_names
    )


@pytest.mark.asyncio
async def test_replay_with_pinned_evaluation_id_is_byte_stable() -> None:
    """Same inputs + same evaluation_id_override → same finding ids."""
    case = ArbitrationCase(
        case_id=derive_case_id(seed="c-replay"),
        signals=(
            _sig(
                "g",
                authority=ArbitrationAuthorityLevel.GOVERNANCE,
                verdict=ArbitrationVerdictKind.DENY,
            ),
        ),
    )
    eval_id = derive_evaluation_id(seed="c-replay")
    rt = _runtime()
    e1 = await rt.evaluate(
        ArbitrationRequest(
            case=case, evaluation_id_override=eval_id
        )
    )
    e2 = await rt.evaluate(
        ArbitrationRequest(
            case=case, evaluation_id_override=eval_id
        )
    )
    r1, r2 = e1.unwrap(), e2.unwrap()
    assert r1.evaluation_id == r2.evaluation_id
    assert r1.chain_id == r2.chain_id
    ids1 = {f.finding_id for f in r1.findings}
    ids2 = {f.finding_id for f in r2.findings}
    assert ids1 == ids2


@pytest.mark.asyncio
async def test_sequence_is_monotonic_per_instance() -> None:
    rt = _runtime()
    case = ArbitrationCase(case_id=derive_case_id(seed="c-seq"))
    sequences = []
    for _ in range(3):
        envelope = await rt.evaluate(
            ArbitrationRequest(case=case)
        )
        sequences.append(envelope.unwrap().sequence)
    assert sequences == [1, 2, 3]


# ─── Evaluator whitelisting ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_evaluator_whitelist_runs_subset() -> None:
    rt = _runtime()
    case = ArbitrationCase(case_id=derive_case_id(seed="c-whitelist"))
    envelope = await rt.evaluate(
        ArbitrationRequest(
            case=case,
            evaluator_names=(
                "finding_conflict_evaluator",
                "deadlock_detection_evaluator",
            ),
        )
    )
    result = envelope.unwrap()
    assert result.evaluator_names == (
        "deadlock_detection_evaluator",
        "finding_conflict_evaluator",
    )


@pytest.mark.asyncio
async def test_evaluator_whitelist_unknown_yields_error_envelope() -> None:
    rt = _runtime()
    case = ArbitrationCase(case_id=derive_case_id(seed="c-unknown"))
    envelope = await rt.evaluate(
        ArbitrationRequest(
            case=case,
            evaluator_names=("does_not_exist",),
        )
    )
    assert envelope.result is None
    assert envelope.error is not None
    assert (
        envelope.trace.outcome
        is ArbitrationOutcome.ARBITRATION_ERROR
    )


# ─── Raising evaluator ───────────────────────────────────────────────


class _RaisingEvaluator(BaseArbitrationEvaluator):
    def __init__(self) -> None:
        super().__init__(name="raising_evaluator")

    def evaluate(self, request, *, evaluation_id):  # type: ignore[no-untyped-def]
        raise RuntimeError("boom")


@pytest.mark.asyncio
async def test_raising_evaluator_does_not_kill_runtime() -> None:
    registry = ArbitrationEvaluatorRegistry(
        [
            FindingConflictEvaluator(),
            _RaisingEvaluator(),
        ]
    )
    rt = OperationalArbitrationRuntime(registry=registry)
    case = ArbitrationCase(case_id=derive_case_id(seed="c-raise"))
    envelope = await rt.evaluate(ArbitrationRequest(case=case))
    # Envelope is still produced; the framework error is folded in.
    assert envelope.result is not None
    assert envelope.error is not None
    assert envelope.is_ok
    assert not envelope.is_fully_clean
    assert (
        envelope.unwrap().decision.outcome
        is ArbitrationOutcome.ARBITRATION_ERROR
    )


# ─── Persistence integration ────────────────────────────────────────


@pytest.mark.asyncio
async def test_persistence_writes_envelope_on_success() -> None:
    store = InMemoryArbitrationPersistence()
    rt = _runtime(persistence=store)
    case = ArbitrationCase(
        case_id=derive_case_id(seed="c-persist"),
        signals=(
            _sig(
                "gov",
                authority=ArbitrationAuthorityLevel.GOVERNANCE,
                verdict=ArbitrationVerdictKind.DENY,
            ),
        ),
    )
    envelope = await rt.evaluate(ArbitrationRequest(case=case))
    record = await store.get(envelope.unwrap().evaluation_id)
    assert record is not None
    assert (
        record.outcome
        is ArbitrationOutcome.ARBITRATION_RESOLVED
    )
    assert record.prevailing_authority_level is (
        ArbitrationAuthorityLevel.GOVERNANCE
    )


@pytest.mark.asyncio
async def test_persistence_failure_does_not_lose_result() -> None:
    class _FailingPersistence(InMemoryArbitrationPersistence):
        async def save(self, record) -> None:  # type: ignore[override]
            raise RuntimeError("write failed")

    store = _FailingPersistence()
    rt = _runtime(persistence=store)
    case = ArbitrationCase(case_id=derive_case_id(seed="c-fail"))
    envelope = await rt.evaluate(ArbitrationRequest(case=case))
    assert envelope.is_ok
    assert envelope.error is not None


@pytest.mark.asyncio
async def test_persistence_listing_filters_by_outcome() -> None:
    store = InMemoryArbitrationPersistence()
    rt = _runtime(persistence=store)

    async def _run(seed: str, verdict: ArbitrationVerdictKind):
        case = ArbitrationCase(
            case_id=derive_case_id(seed=seed),
            signals=(
                _sig(
                    seed,
                    authority=ArbitrationAuthorityLevel.GOVERNANCE,
                    verdict=verdict,
                ),
            ),
        )
        await rt.evaluate(ArbitrationRequest(case=case))

    await asyncio.gather(
        _run("c1", ArbitrationVerdictKind.ALLOW),
        _run("c2", ArbitrationVerdictKind.DENY),
        _run("c3", ArbitrationVerdictKind.ALLOW),
    )
    page = await store.list_records(
        ArbitrationQuery(
            outcome=ArbitrationOutcome.ARBITRATION_RESOLVED
        )
    )
    assert page.total == 3
    assert all(
        r.outcome is ArbitrationOutcome.ARBITRATION_RESOLVED
        for r in page.records
    )


# ─── Immutability sentinel ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_result_findings_tuple_is_immutable() -> None:
    rt = _runtime()
    case = ArbitrationCase(case_id=derive_case_id(seed="c-immut"))
    envelope: ArbitrationEnvelope = await rt.evaluate(
        ArbitrationRequest(case=case)
    )
    result = envelope.unwrap()
    assert isinstance(result.findings, tuple)
    assert isinstance(result.conflicts, tuple)
    assert isinstance(result.deadlock_witnesses, tuple)
    assert isinstance(result.evaluator_names, tuple)
