"""Sprint K — pure aggregation function semantics.

Properties pinned:

* deterministic decision_id when passed explicitly,
* most-severe-wins escalation,
* CRITICAL → REJECT + HALT escalation,
* HIGH     → ESCALATE + REVIEW escalation,
* MEDIUM   → ANNOTATE + NOTICE escalation,
* LOW/INFO → ACCEPT (or ANNOTATE if any non-INFO),
* findings are concatenated in sorted-evaluator-name order,
* weighted-average score honours `scoring_weights`,
* SKIPPED / ERRORED evaluators are excluded from the score average,
* identical inputs (with fixed decision_id) produce byte-identical
  outputs.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.supervisor.contracts.decisions import build_supervisor_decision
from app.supervisor.contracts.evaluations import QAEvaluation
from app.supervisor.enums import (
    EscalationLevel,
    EvaluationStatus,
    FindingCategory,
    FindingSeverity,
    SupervisorDecisionKind,
)
from app.supervisor.models.evidence import EvaluationEvidence
from app.supervisor.models.findings import RuntimeFinding


# ─── Helpers ─────────────────────────────────────────────────────────


_NOW = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
_EXEC = uuid.UUID("00000000-0000-0000-0000-000000000001")


def _finding(
    *,
    evaluator: str = "x",
    code: str = "x.found",
    severity: FindingSeverity = FindingSeverity.LOW,
    finding_id: uuid.UUID | None = None,
) -> RuntimeFinding:
    return RuntimeFinding(
        finding_id=finding_id or uuid.uuid4(),
        evaluator_name=evaluator,
        category=FindingCategory.OTHER,
        severity=severity,
        code=code,
        message="",
        evidence=EvaluationEvidence(execution_id=_EXEC),
        detected_at=_NOW,
    )


def _evaluation(
    *,
    name: str,
    status: EvaluationStatus = EvaluationStatus.PASSED,
    score: float = 1.0,
    findings: tuple[RuntimeFinding, ...] = (),
) -> QAEvaluation:
    return QAEvaluation(
        evaluator_name=name,
        status=status,
        score=score,
        findings=findings,
        started_at=_NOW,
        ended_at=_NOW,
        latency_ms=0.0,
    )


# ─── Tests ───────────────────────────────────────────────────────────


def test_no_evaluations_yields_accept() -> None:
    decision = build_supervisor_decision(evaluations=())
    assert decision.kind is SupervisorDecisionKind.ACCEPT
    assert decision.aggregate_score == 1.0
    assert decision.findings == ()
    assert decision.escalations == ()


def test_clean_evaluations_yield_accept() -> None:
    decision = build_supervisor_decision(
        evaluations=(_evaluation(name="a"), _evaluation(name="b")),
    )
    assert decision.kind is SupervisorDecisionKind.ACCEPT
    assert decision.aggregate_score == 1.0
    assert decision.escalations == ()


def test_critical_finding_triggers_reject_and_halt() -> None:
    finding = _finding(severity=FindingSeverity.CRITICAL)
    decision = build_supervisor_decision(
        evaluations=(
            _evaluation(
                name="a",
                status=EvaluationStatus.FAILED,
                score=0.0,
                findings=(finding,),
            ),
        ),
        decision_id=uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
    )
    assert decision.kind is SupervisorDecisionKind.REJECT
    assert decision.requires_escalation
    assert len(decision.escalations) == 1
    assert decision.escalations[0].level is EscalationLevel.HALT
    assert finding.finding_id in decision.escalations[0].triggering_finding_ids


def test_high_finding_triggers_escalate_and_review() -> None:
    finding = _finding(severity=FindingSeverity.HIGH)
    decision = build_supervisor_decision(
        evaluations=(
            _evaluation(
                name="a",
                status=EvaluationStatus.FAILED,
                score=0.0,
                findings=(finding,),
            ),
        ),
    )
    assert decision.kind is SupervisorDecisionKind.ESCALATE
    assert decision.escalations[0].level is EscalationLevel.REVIEW


def test_medium_finding_triggers_annotate_and_notice() -> None:
    finding = _finding(severity=FindingSeverity.MEDIUM)
    decision = build_supervisor_decision(
        evaluations=(
            _evaluation(
                name="a",
                status=EvaluationStatus.WARNING,
                score=0.5,
                findings=(finding,),
            ),
        ),
    )
    assert decision.kind is SupervisorDecisionKind.ANNOTATE
    assert decision.escalations[0].level is EscalationLevel.NOTICE


def test_low_findings_yield_annotate_no_escalation() -> None:
    decision = build_supervisor_decision(
        evaluations=(
            _evaluation(
                name="a",
                status=EvaluationStatus.WARNING,
                score=0.9,
                findings=(_finding(severity=FindingSeverity.LOW),),
            ),
        ),
    )
    assert decision.kind is SupervisorDecisionKind.ANNOTATE
    assert decision.escalations == ()


def test_info_only_yields_accept() -> None:
    decision = build_supervisor_decision(
        evaluations=(
            _evaluation(
                name="a",
                status=EvaluationStatus.WARNING,
                score=0.95,
                findings=(_finding(severity=FindingSeverity.INFO),),
            ),
        ),
    )
    assert decision.kind is SupervisorDecisionKind.ACCEPT
    assert decision.findings != ()  # INFO findings still attached
    assert decision.escalations == ()


def test_most_severe_wins() -> None:
    findings = (
        _finding(severity=FindingSeverity.LOW, code="a.low"),
        _finding(severity=FindingSeverity.HIGH, code="a.high"),
        _finding(severity=FindingSeverity.MEDIUM, code="a.medium"),
    )
    decision = build_supervisor_decision(
        evaluations=(
            _evaluation(
                name="a",
                status=EvaluationStatus.FAILED,
                score=0.2,
                findings=findings,
            ),
        ),
    )
    assert decision.kind is SupervisorDecisionKind.ESCALATE
    # Only the HIGH-severity finding triggers the REVIEW escalation.
    assert len(decision.escalations[0].triggering_finding_ids) == 1


def test_findings_concatenated_in_sorted_evaluator_order() -> None:
    f_b = _finding(evaluator="b_evaluator", code="b")
    f_a = _finding(evaluator="a_evaluator", code="a")
    decision = build_supervisor_decision(
        evaluations=(
            _evaluation(
                name="b_evaluator",
                status=EvaluationStatus.WARNING,
                score=0.5,
                findings=(f_b,),
            ),
            _evaluation(
                name="a_evaluator",
                status=EvaluationStatus.WARNING,
                score=0.5,
                findings=(f_a,),
            ),
        ),
    )
    # a_evaluator's findings come first by sort order.
    assert decision.findings[0].evaluator_name == "a_evaluator"
    assert decision.findings[1].evaluator_name == "b_evaluator"


def test_weighted_score_average() -> None:
    decision = build_supervisor_decision(
        evaluations=(
            _evaluation(name="a", score=0.0),
            _evaluation(name="b", score=1.0),
        ),
        scoring_weights={"a": 1.0, "b": 3.0},
    )
    # (0 * 1 + 1 * 3) / (1 + 3) = 0.75
    assert decision.aggregate_score == 0.75


def test_skipped_evaluators_excluded_from_score() -> None:
    decision = build_supervisor_decision(
        evaluations=(
            _evaluation(name="a", score=0.5),
            _evaluation(name="b", status=EvaluationStatus.SKIPPED, score=1.0),
        ),
    )
    assert decision.aggregate_score == 0.5


def test_errored_evaluators_excluded_from_score() -> None:
    decision = build_supervisor_decision(
        evaluations=(
            _evaluation(name="a", score=0.7),
            _evaluation(name="b", status=EvaluationStatus.ERRORED, score=0.0),
        ),
    )
    assert decision.aggregate_score == 0.7


def test_replay_decision_is_byte_identical() -> None:
    decision_id = uuid.UUID("11111111-1111-1111-1111-111111111111")
    finding_id = uuid.UUID("22222222-2222-2222-2222-222222222222")
    decided_at = _NOW

    inputs = (
        _evaluation(
            name="a",
            status=EvaluationStatus.FAILED,
            score=0.0,
            findings=(
                _finding(
                    severity=FindingSeverity.CRITICAL, finding_id=finding_id
                ),
            ),
        ),
    )

    d1 = build_supervisor_decision(
        evaluations=inputs,
        decision_id=decision_id,
        decided_at=decided_at,
    )
    d2 = build_supervisor_decision(
        evaluations=inputs,
        decision_id=decision_id,
        decided_at=decided_at,
    )
    assert d1 == d2
    assert d1.escalations == d2.escalations
