"""Per-evaluator behaviour tests for the five built-in evaluators."""

from __future__ import annotations

from app.arbitration.contracts.requests import ArbitrationRequest
from app.arbitration.enums import (
    ArbitrationAuthorityLevel,
    ArbitrationConflictKind,
    ArbitrationDeadlockKind,
    ArbitrationOutcome,
    ArbitrationVerdictKind,
)
from app.arbitration.evaluators.builtin import (
    DeadlockDetectionEvaluator,
    EscalationConflictEvaluator,
    FindingConflictEvaluator,
    RecommendationConflictEvaluator,
    SupervisorDisagreementEvaluator,
)
from app.arbitration.evaluators.builtin.escalation_conflict import (
    ESCALATION_TARGET_METADATA_KEY,
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
from app.arbitration.taxonomy import ArbitrationFindingCode


def _sig(
    seed: str,
    *,
    authority: ArbitrationAuthorityLevel,
    verdict: ArbitrationVerdictKind,
    source_substrate: str = "test",
    metadata: dict[str, object] | None = None,
) -> ArbitrationSignal:
    return ArbitrationSignal(
        signal_id=derive_signal_id(seed=seed),
        authority=authority,
        verdict=verdict,
        source_substrate=source_substrate,
        source_id=seed,
        metadata=metadata or {},
    )


def _rec(
    seed: str,
    *,
    authority: ArbitrationAuthorityLevel,
    directive: str,
    source_substrate: str = "test",
) -> ArbitrationRecommendation:
    return ArbitrationRecommendation(
        recommendation_id=derive_recommendation_id(seed=seed),
        authority=authority,
        directive=directive,
        source_substrate=source_substrate,
        source_id=seed,
    )


def _request(case: ArbitrationCase) -> ArbitrationRequest:
    return ArbitrationRequest(case=case)


def _eval_id():
    return derive_evaluation_id(seed="e1")


# ─── FindingConflictEvaluator ────────────────────────────────────────


def test_finding_conflict_emits_no_conflict_when_consistent() -> None:
    case = ArbitrationCase(
        case_id=derive_case_id(seed="c1"),
        signals=(
            _sig(
                "a",
                authority=ArbitrationAuthorityLevel.SUPERVISOR,
                verdict=ArbitrationVerdictKind.PASS,
            ),
            _sig(
                "b",
                authority=ArbitrationAuthorityLevel.SUPERVISOR,
                verdict=ArbitrationVerdictKind.PASS,
            ),
        ),
    )
    output = FindingConflictEvaluator().evaluate(
        _request(case), evaluation_id=_eval_id()
    )
    assert len(output.conflicts) == 0
    assert any(
        f.code == ArbitrationFindingCode.NO_CONFLICT.value
        for f in output.findings
    )


def test_finding_conflict_emits_authorisation_contradiction() -> None:
    case = ArbitrationCase(
        case_id=derive_case_id(seed="c1"),
        signals=(
            _sig(
                "a",
                authority=ArbitrationAuthorityLevel.SUPERVISOR,
                verdict=ArbitrationVerdictKind.ALLOW,
            ),
            _sig(
                "b",
                authority=ArbitrationAuthorityLevel.SUPERVISOR,
                verdict=ArbitrationVerdictKind.DENY,
            ),
        ),
    )
    output = FindingConflictEvaluator().evaluate(
        _request(case), evaluation_id=_eval_id()
    )
    assert len(output.conflicts) == 1
    assert (
        output.conflicts[0].kind
        is ArbitrationConflictKind.AUTHORISATION_CONFLICT
    )
    assert any(
        f.outcome_hint is ArbitrationOutcome.ARBITRATION_CONFLICT
        for f in output.findings
    )


def test_finding_conflict_emits_quality_contradiction() -> None:
    case = ArbitrationCase(
        case_id=derive_case_id(seed="c1"),
        signals=(
            _sig(
                "a",
                authority=ArbitrationAuthorityLevel.SUPERVISOR,
                verdict=ArbitrationVerdictKind.PASS,
            ),
            _sig(
                "b",
                authority=ArbitrationAuthorityLevel.SUPERVISOR,
                verdict=ArbitrationVerdictKind.FAIL,
            ),
        ),
    )
    output = FindingConflictEvaluator().evaluate(
        _request(case), evaluation_id=_eval_id()
    )
    assert (
        output.conflicts[0].kind
        is ArbitrationConflictKind.QUALITY_CONFLICT
    )


def test_finding_conflict_emits_cross_axis_contradiction() -> None:
    case = ArbitrationCase(
        case_id=derive_case_id(seed="c1"),
        signals=(
            _sig(
                "a",
                authority=ArbitrationAuthorityLevel.POLICY,
                verdict=ArbitrationVerdictKind.ALLOW,
            ),
            _sig(
                "b",
                authority=ArbitrationAuthorityLevel.SUPERVISOR,
                verdict=ArbitrationVerdictKind.UNSAFE,
            ),
        ),
    )
    output = FindingConflictEvaluator().evaluate(
        _request(case), evaluation_id=_eval_id()
    )
    assert (
        output.conflicts[0].kind
        is ArbitrationConflictKind.AUTHORISATION_QUALITY_CROSS
    )


def test_finding_conflict_handles_insufficient_signals() -> None:
    case = ArbitrationCase(case_id=derive_case_id(seed="c1"))
    output = FindingConflictEvaluator().evaluate(
        _request(case), evaluation_id=_eval_id()
    )
    assert len(output.conflicts) == 0
    assert (
        output.findings[0].code
        == ArbitrationFindingCode.INSUFFICIENT_SIGNALS.value
    )


# ─── RecommendationConflictEvaluator ─────────────────────────────────


def test_recommendation_conflict_detects_directive_mismatch() -> None:
    case = ArbitrationCase(
        case_id=derive_case_id(seed="c2"),
        recommendations=(
            _rec(
                "r1",
                authority=ArbitrationAuthorityLevel.SUPERVISOR,
                directive="escalate_to:platform",
            ),
            _rec(
                "r2",
                authority=ArbitrationAuthorityLevel.SUPERVISOR,
                directive="proceed",
            ),
        ),
    )
    output = RecommendationConflictEvaluator().evaluate(
        _request(case), evaluation_id=_eval_id()
    )
    assert len(output.conflicts) == 1
    assert (
        output.conflicts[0].kind
        is ArbitrationConflictKind.RECOMMENDATION_CONFLICT
    )


def test_recommendation_conflict_agreement_emits_no_conflict() -> None:
    case = ArbitrationCase(
        case_id=derive_case_id(seed="c2"),
        recommendations=(
            _rec(
                "r1",
                authority=ArbitrationAuthorityLevel.SUPERVISOR,
                directive="proceed",
            ),
            _rec(
                "r2",
                authority=ArbitrationAuthorityLevel.SUPERVISOR,
                directive="proceed",
            ),
        ),
    )
    output = RecommendationConflictEvaluator().evaluate(
        _request(case), evaluation_id=_eval_id()
    )
    assert output.conflicts == ()


# ─── EscalationConflictEvaluator ─────────────────────────────────────


def test_escalation_conflict_detects_escalate_vs_allow() -> None:
    case = ArbitrationCase(
        case_id=derive_case_id(seed="c3"),
        signals=(
            _sig(
                "a",
                authority=ArbitrationAuthorityLevel.SUPERVISOR,
                verdict=ArbitrationVerdictKind.ESCALATE,
            ),
            _sig(
                "b",
                authority=ArbitrationAuthorityLevel.SUPERVISOR,
                verdict=ArbitrationVerdictKind.ALLOW,
            ),
        ),
    )
    output = EscalationConflictEvaluator().evaluate(
        _request(case), evaluation_id=_eval_id()
    )
    assert any(
        c.kind is ArbitrationConflictKind.ESCALATION_CONFLICT
        for c in output.conflicts
    )


def test_escalation_conflict_detects_target_mismatch() -> None:
    case = ArbitrationCase(
        case_id=derive_case_id(seed="c3"),
        signals=(
            _sig(
                "a",
                authority=ArbitrationAuthorityLevel.SUPERVISOR,
                verdict=ArbitrationVerdictKind.ESCALATE,
                metadata={
                    ESCALATION_TARGET_METADATA_KEY: "team_lead"
                },
            ),
            _sig(
                "b",
                authority=ArbitrationAuthorityLevel.SUPERVISOR,
                verdict=ArbitrationVerdictKind.ESCALATE,
                metadata={
                    ESCALATION_TARGET_METADATA_KEY: "ops_lead"
                },
            ),
        ),
    )
    output = EscalationConflictEvaluator().evaluate(
        _request(case), evaluation_id=_eval_id()
    )
    assert any(
        c.kind is ArbitrationConflictKind.ESCALATION_CONFLICT
        for c in output.conflicts
    )


def test_escalation_conflict_no_escalations_emits_no_conflict() -> None:
    case = ArbitrationCase(
        case_id=derive_case_id(seed="c3"),
        signals=(
            _sig(
                "a",
                authority=ArbitrationAuthorityLevel.SUPERVISOR,
                verdict=ArbitrationVerdictKind.ALLOW,
            ),
        ),
    )
    output = EscalationConflictEvaluator().evaluate(
        _request(case), evaluation_id=_eval_id()
    )
    assert output.conflicts == ()


# ─── SupervisorDisagreementEvaluator ─────────────────────────────────


def test_supervisor_disagreement_only_considers_supervisor_signals() -> None:
    case = ArbitrationCase(
        case_id=derive_case_id(seed="c4"),
        signals=(
            _sig(
                "a",
                authority=ArbitrationAuthorityLevel.SUPERVISOR,
                verdict=ArbitrationVerdictKind.PASS,
            ),
            _sig(
                "b",
                authority=ArbitrationAuthorityLevel.GOVERNANCE,
                verdict=ArbitrationVerdictKind.FAIL,
            ),
        ),
    )
    output = SupervisorDisagreementEvaluator().evaluate(
        _request(case), evaluation_id=_eval_id()
    )
    # Only one supervisor signal → INSUFFICIENT_SIGNALS.
    assert (
        output.findings[0].code
        == ArbitrationFindingCode.INSUFFICIENT_SIGNALS.value
    )


def test_supervisor_disagreement_surfaces_verdict_mismatch() -> None:
    case = ArbitrationCase(
        case_id=derive_case_id(seed="c4"),
        signals=(
            _sig(
                "a",
                authority=ArbitrationAuthorityLevel.SUPERVISOR,
                verdict=ArbitrationVerdictKind.ALLOW,
            ),
            _sig(
                "b",
                authority=ArbitrationAuthorityLevel.SUPERVISOR,
                verdict=ArbitrationVerdictKind.ESCALATE,
            ),
        ),
    )
    output = SupervisorDisagreementEvaluator().evaluate(
        _request(case), evaluation_id=_eval_id()
    )
    assert any(
        c.kind is ArbitrationConflictKind.SUPERVISOR_DISAGREEMENT
        for c in output.conflicts
    )


def test_supervisor_disagreement_surfaces_directive_mismatch() -> None:
    case = ArbitrationCase(
        case_id=derive_case_id(seed="c4"),
        recommendations=(
            _rec(
                "r1",
                authority=ArbitrationAuthorityLevel.SUPERVISOR,
                directive="proceed",
            ),
            _rec(
                "r2",
                authority=ArbitrationAuthorityLevel.SUPERVISOR,
                directive="escalate",
            ),
        ),
    )
    output = SupervisorDisagreementEvaluator().evaluate(
        _request(case), evaluation_id=_eval_id()
    )
    assert any(
        c.kind is ArbitrationConflictKind.SUPERVISOR_DISAGREEMENT
        for c in output.conflicts
    )


# ─── DeadlockDetectionEvaluator ──────────────────────────────────────


def test_deadlock_detection_iteration_exhausted() -> None:
    case = ArbitrationCase(
        case_id=derive_case_id(seed="c5"),
        iteration_count=3,
        max_iterations=3,
    )
    output = DeadlockDetectionEvaluator().evaluate(
        _request(case), evaluation_id=_eval_id()
    )
    assert any(
        w.kind is ArbitrationDeadlockKind.ITERATION_EXHAUSTED
        for w in output.deadlock_witnesses
    )


def test_deadlock_detection_cyclic_case_lineage() -> None:
    cid = derive_case_id(seed="repeat")
    case = ArbitrationCase(
        case_id=derive_case_id(seed="c5"),
        prior_case_ids=(cid, cid),
        iteration_count=2,
    )
    output = DeadlockDetectionEvaluator().evaluate(
        _request(case), evaluation_id=_eval_id()
    )
    assert any(
        w.kind is ArbitrationDeadlockKind.CYCLIC_CASE_LINEAGE
        for w in output.deadlock_witnesses
    )


def test_deadlock_detection_contradictory_escalation_chain() -> None:
    case = ArbitrationCase(
        case_id=derive_case_id(seed="c5"),
        signals=(
            _sig(
                "a",
                authority=ArbitrationAuthorityLevel.SUPERVISOR,
                verdict=ArbitrationVerdictKind.ESCALATE,
                source_substrate="supervisor",
                metadata={
                    ESCALATION_TARGET_METADATA_KEY: "team_lead"
                },
            ),
            _sig(
                "b",
                authority=ArbitrationAuthorityLevel.SUPERVISOR,
                verdict=ArbitrationVerdictKind.ESCALATE,
                source_substrate="supervisor",
                metadata={
                    ESCALATION_TARGET_METADATA_KEY: "ops_lead"
                },
            ),
        ),
    )
    output = DeadlockDetectionEvaluator().evaluate(
        _request(case), evaluation_id=_eval_id()
    )
    assert any(
        w.kind
        is ArbitrationDeadlockKind.CONTRADICTORY_ESCALATION_CHAIN
        for w in output.deadlock_witnesses
    )


def test_deadlock_detection_emits_risk_when_iteration_above_one() -> None:
    case = ArbitrationCase(
        case_id=derive_case_id(seed="c5"),
        iteration_count=2,
        max_iterations=5,
    )
    output = DeadlockDetectionEvaluator().evaluate(
        _request(case), evaluation_id=_eval_id()
    )
    assert output.deadlock_witnesses == ()
    assert any(
        f.code == ArbitrationFindingCode.DEADLOCK_RISK.value
        for f in output.findings
    )


def test_deadlock_detection_clean_case_emits_no_conflict() -> None:
    case = ArbitrationCase(case_id=derive_case_id(seed="c5"))
    output = DeadlockDetectionEvaluator().evaluate(
        _request(case), evaluation_id=_eval_id()
    )
    assert output.deadlock_witnesses == ()
    assert any(
        f.code == ArbitrationFindingCode.NO_CONFLICT.value
        for f in output.findings
    )
