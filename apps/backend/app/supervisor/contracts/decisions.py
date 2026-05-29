"""Supervisor decisions + the pure aggregation function.

Three things in one file (same pattern as `app/governance/decisions.py`):

* `EscalationDecision`         — an explicit escalation handoff,
* `SupervisorDecision`         — the apex aggregated verdict,
* `build_supervisor_decision`  — the **single** pure function that
                                  collapses evaluator outputs into a
                                  decision.

The aggregation rule is "most severe wins" applied across all
findings produced by all evaluators. Sprint K does not act on the
recommendation — orchestration code respects the decision in a way
that is its choice.

Determinism guarantee: given fixed `(evaluations, scoring_weights,
decided_at, decision_id)`, `build_supervisor_decision` returns a
byte-identical `SupervisorDecision`. Pass an explicit `decision_id`
for replay tests; production callers let the function generate
`uuid4`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence, cast

from app.core.deterministic_identity import derive_runtime_id
from app.supervisor.enums import (
    EscalationLevel,
    EvaluationStatus,
    FindingSeverity,
    SupervisorDecisionKind,
)
from app.supervisor.identity import derive_escalation_id
from app.supervisor.models.findings import RuntimeFinding

_DECISION_NAMESPACE = uuid.UUID("e4ed8a1a-13be-4ac1-bd19-1a2dbe50600f")


@dataclass(frozen=True, slots=True)
class EscalationDecision:
    """One explicit escalation recommendation.

    Sprint K records the recommendation; downstream orchestration
    code chooses how to respect it (logging, paging, halting an
    enclosing pipeline). The supervisor never acts.
    """

    escalation_id: uuid.UUID
    level: EscalationLevel
    reason: str
    triggering_finding_ids: tuple[uuid.UUID, ...]
    decided_at: datetime
    metadata: dict[str, Any] = field(default_factory=dict[str, Any])


@dataclass(frozen=True, slots=True)
class SupervisorDecision:
    """Apex aggregated supervisor verdict.

    Attributes:
        decision_id:        Stable UUID for cross-system correlation.
        kind:                Disposition (`ACCEPT` / `ANNOTATE` /
                             `ESCALATE` / `REJECT`).
        aggregate_score:     Weighted average of per-evaluator scores
                             (1.0 = best, 0.0 = worst). Evaluators
                             whose status is `ERRORED` contribute 0;
                             `SKIPPED` evaluators are excluded from
                             the average.
        findings:            All emitted findings in evaluator-sort
                             order, preserving each evaluator's
                             internal order. Empty when ACCEPT.
        escalations:         Zero or more `EscalationDecision`s.
                             Aggregated by level — at most one per
                             distinct `EscalationLevel`.
        reason:               Short human-readable explanation.
        decided_at:          When the aggregator produced the decision.
        metadata:            Caller-supplied, free-form.
    """

    decision_id: uuid.UUID
    kind: SupervisorDecisionKind
    aggregate_score: float
    findings: tuple[RuntimeFinding, ...]
    escalations: tuple[EscalationDecision, ...]
    reason: str
    decided_at: datetime
    metadata: dict[str, Any] = field(default_factory=dict[str, Any])

    @property
    def is_accept(self) -> bool:
        return self.kind is SupervisorDecisionKind.ACCEPT

    @property
    def requires_escalation(self) -> bool:
        return self.kind in {
            SupervisorDecisionKind.ESCALATE,
            SupervisorDecisionKind.REJECT,
        }


# ─── Pure aggregation ────────────────────────────────────────────────


def build_supervisor_decision(
    *,
    evaluations: Sequence["object"],  # `QAEvaluation` — forward import
    scoring_weights: Mapping[str, float] | None = None,
    decided_at: datetime | None = None,
    decision_id: uuid.UUID | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> SupervisorDecision:
    """Collapse evaluator outputs into one `SupervisorDecision`.

    Rules (deterministic, total):

    1. **Findings** are concatenated in sorted-evaluator-name order,
       preserving each evaluator's internal ordering. The full list
       lands on `SupervisorDecision.findings`.

    2. **Aggregate score** is the weighted average of per-evaluator
       scores. Default weight is 1.0 per evaluator; pass
       `scoring_weights={name: weight}` to override. `SKIPPED` and
       `ERRORED` evaluators are excluded from the average (a SKIPPED
       evaluator should not lower the score; an ERRORED evaluator is
       surfaced as a meta-finding by the runtime, not here).

    3. **Escalation level** is derived from the maximum finding
       severity:

           CRITICAL → HALT
           HIGH     → REVIEW
           MEDIUM   → NOTICE
           LOW/INFO → NONE

       At most one escalation per level is emitted. The triggering
       finding ids are every finding *whose severity matches the
       escalation's severity threshold*.

    4. **Decision kind**:

           HALT escalation  → REJECT
           REVIEW escalation→ ESCALATE
           NOTICE escalation→ ANNOTATE (plus a NOTICE escalation)
           No escalation + any non-INFO finding → ANNOTATE
           No escalation + no findings (or only INFO) → ACCEPT

    Determinism: identical inputs produce identical outputs, modulo
    the wall-clock `decided_at` when not explicitly supplied. Pass an
    explicit `decision_id` to lock that field too.
    """
    from app.supervisor.contracts.evaluations import QAEvaluation

    typed_evaluations = cast(tuple[QAEvaluation, ...], tuple(evaluations))
    decided_at = decided_at or datetime.now(timezone.utc)
    decision_id = decision_id or derive_runtime_id(
        namespace=_DECISION_NAMESPACE,
        tenant_id=None,
        seed_components=(
            "supervisor_decision",
            _evaluation_seed(typed_evaluations),
            metadata,
            scoring_weights,
        ),
    )
    weights = dict(scoring_weights or {})

    # 1. Findings concatenated in sorted-evaluator-name order.
    sorted_evals = sorted(typed_evaluations, key=lambda e: e.evaluator_name)
    findings: tuple[RuntimeFinding, ...] = tuple(
        finding
        for evaluation in sorted_evals
        for finding in evaluation.findings
    )

    # 2. Aggregate score — weighted average over PASSED/WARNING/FAILED.
    scoring_evals = [
        e
        for e in sorted_evals
        if e.status
        in {
            EvaluationStatus.PASSED,
            EvaluationStatus.WARNING,
            EvaluationStatus.FAILED,
        }
    ]
    if scoring_evals:
        total_weight = sum(weights.get(e.evaluator_name, 1.0) for e in scoring_evals)
        if total_weight > 0:
            aggregate_score = (
                sum(
                    weights.get(e.evaluator_name, 1.0) * e.score
                    for e in scoring_evals
                )
                / total_weight
            )
        else:
            aggregate_score = 0.0
    else:
        # No evaluator produced a scorable verdict. Score is neutral.
        aggregate_score = 1.0

    # 3. Escalation level from max finding severity.
    max_severity = _max_severity(findings)
    level = _severity_to_escalation(max_severity)

    escalations: tuple[EscalationDecision, ...] = ()
    if level is not EscalationLevel.NONE:
        triggering = tuple(
            f.finding_id
            for f in findings
            if _severity_to_escalation(f.severity) is level
        )
        escalations = (
            EscalationDecision(
                escalation_id=derive_escalation_id(
                    decision_id=decision_id, level=level.value
                ),
                level=level,
                reason=_escalation_reason(level, max_severity, len(triggering)),
                triggering_finding_ids=triggering,
                decided_at=decided_at,
            ),
        )

    # 4. Decision kind from escalation + findings.
    kind = _decide_kind(level, findings)
    reason = _decision_reason(kind, level, max_severity, len(findings))

    return SupervisorDecision(
        decision_id=decision_id,
        kind=kind,
        aggregate_score=aggregate_score,
        findings=findings,
        escalations=escalations,
        reason=reason,
        decided_at=decided_at,
        metadata=dict(metadata or {}),
    )


def _evaluation_seed(
    evaluations: Sequence["object"],
) -> tuple[tuple[object, ...], ...]:
    from app.supervisor.contracts.evaluations import QAEvaluation

    typed = cast(tuple[QAEvaluation, ...], tuple(evaluations))
    return tuple(
        (
            evaluation.evaluator_name,
            evaluation.status.value,
            round(evaluation.score, 8),
            tuple(
                (
                    str(finding.finding_id),
                    finding.evaluator_name,
                    finding.category.value,
                    finding.severity.value,
                    finding.code,
                    finding.message,
                    finding.metadata,
                )
                for finding in evaluation.findings
            ),
            evaluation.error,
            evaluation.metadata,
        )
        for evaluation in typed
    )


# ─── Pure helpers ────────────────────────────────────────────────────


_SEVERITY_ORDER: tuple[FindingSeverity, ...] = (
    FindingSeverity.INFO,
    FindingSeverity.LOW,
    FindingSeverity.MEDIUM,
    FindingSeverity.HIGH,
    FindingSeverity.CRITICAL,
)


def _severity_rank(severity: FindingSeverity) -> int:
    return _SEVERITY_ORDER.index(severity)


def _max_severity(findings: Sequence[RuntimeFinding]) -> FindingSeverity | None:
    if not findings:
        return None
    return max(findings, key=lambda f: _severity_rank(f.severity)).severity


def _severity_to_escalation(
    severity: FindingSeverity | None,
) -> EscalationLevel:
    if severity is None:
        return EscalationLevel.NONE
    if severity is FindingSeverity.CRITICAL:
        return EscalationLevel.HALT
    if severity is FindingSeverity.HIGH:
        return EscalationLevel.REVIEW
    if severity is FindingSeverity.MEDIUM:
        return EscalationLevel.NOTICE
    return EscalationLevel.NONE


def _decide_kind(
    level: EscalationLevel,
    findings: tuple[RuntimeFinding, ...],
) -> SupervisorDecisionKind:
    if level is EscalationLevel.HALT:
        return SupervisorDecisionKind.REJECT
    if level is EscalationLevel.REVIEW:
        return SupervisorDecisionKind.ESCALATE
    if level is EscalationLevel.NOTICE:
        return SupervisorDecisionKind.ANNOTATE
    # NONE escalation: ANNOTATE iff any non-INFO finding, else ACCEPT.
    has_non_info = any(
        f.severity is not FindingSeverity.INFO for f in findings
    )
    if has_non_info or findings:
        return (
            SupervisorDecisionKind.ANNOTATE
            if has_non_info
            else SupervisorDecisionKind.ACCEPT
        )
    return SupervisorDecisionKind.ACCEPT


def _escalation_reason(
    level: EscalationLevel,
    severity: FindingSeverity | None,
    count: int,
) -> str:
    sev = severity.value if severity is not None else "none"
    return f"{level.value}: {count} finding(s) at severity {sev}"


def _decision_reason(
    kind: SupervisorDecisionKind,
    level: EscalationLevel,
    severity: FindingSeverity | None,
    finding_count: int,
) -> str:
    if kind is SupervisorDecisionKind.ACCEPT:
        return "no findings of concern"
    sev = severity.value if severity is not None else "none"
    return (
        f"{kind.value}: {finding_count} finding(s), max severity {sev}, "
        f"escalation {level.value}"
    )


__all__ = [
    "EscalationDecision",
    "SupervisorDecision",
    "build_supervisor_decision",
]
