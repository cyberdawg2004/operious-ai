"""Governance compliance evaluator.

Inspects every governance decision referenced by the execution.
Findings:

* `governance.deny`             — DENY decision               (HIGH)
* `governance.require_approval` — REQUIRE_APPROVAL decision   (MEDIUM)
* `governance.escalate`         — ESCALATE decision            (HIGH)
* `governance.degrade`          — DEGRADE decision (with
                                   restrictions)               (LOW)

The supervisor does NOT re-evaluate governance — it only inspects the
decisions that the governance runtime produced and flags non-allow
verdicts so audit / replay can correlate them with the execution
outcome.

SKIPS when no governance decisions were recorded.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import ClassVar

from app.governance.enums import Decision
from app.supervisor.contracts.evaluations import QAEvaluation
from app.supervisor.enums import (
    EvaluationStatus,
    FindingCategory,
    FindingSeverity,
)
from app.supervisor.evaluators.base import BaseEvaluator
from app.supervisor.identity import derive_finding_id
from app.supervisor.models.evidence import EvaluationEvidence
from app.supervisor.models.findings import RuntimeFinding
from app.supervisor.models.view import GovernanceDecisionView, InspectionView
from app.supervisor.taxonomy import EvidenceMetadataKey, FindingCode


# Decision-value → (finding-code, severity) classification.
#
# Keyed on `Decision.value` (string) so the supervisor never imports
# the governance runtime / engine — only the canonical enum
# vocabulary. The dict literal references `Decision` enum members
# directly, so a rename in `Decision` surfaces as an import-time
# failure here rather than as silent drift in audit dashboards.
#
# `_validate_decision_classification()` below is invoked at module
# import; it raises if a new non-ALLOW `Decision` value lands without
# a row here. That is the operational tripwire for governance
# vocabulary drift.
_DECISION_CLASSIFICATION: dict[str, tuple[str, FindingSeverity]] = {
    Decision.DENY.value: (FindingCode.GOVERNANCE_DENY.value, FindingSeverity.HIGH),
    Decision.ESCALATE.value: (
        FindingCode.GOVERNANCE_ESCALATE.value,
        FindingSeverity.HIGH,
    ),
    Decision.REQUIRE_APPROVAL.value: (
        FindingCode.GOVERNANCE_REQUIRE_APPROVAL.value,
        FindingSeverity.MEDIUM,
    ),
    Decision.DEGRADE.value: (
        FindingCode.GOVERNANCE_DEGRADE.value,
        FindingSeverity.LOW,
    ),
    Decision.REDACT.value: (
        FindingCode.GOVERNANCE_REDACT.value,
        FindingSeverity.LOW,
    ),
}


def _validate_decision_classification() -> None:
    """Import-time drift check.

    Every non-ALLOW `Decision` enum value MUST have a classification
    row above. New values added to `Decision` without a corresponding
    row here would otherwise silently route through the "unknown"
    fallback path, masking governance-vocabulary changes from
    supervisor audit consumers.
    """
    expected = {d.value for d in Decision if d is not Decision.ALLOW}
    classified = set(_DECISION_CLASSIFICATION.keys())
    missing = expected - classified
    if missing:
        raise RuntimeError(
            "GovernanceComplianceEvaluator: unclassified Decision values "
            f"detected — extend _DECISION_CLASSIFICATION: {sorted(missing)}"
        )


_validate_decision_classification()


class GovernanceComplianceEvaluator(BaseEvaluator):
    """Inspects governance decisions for non-allow verdicts."""

    name: ClassVar[str] = "governance_compliance"

    async def evaluate(self, view: InspectionView) -> QAEvaluation:
        started_at = datetime.now(timezone.utc)

        if not view.governance_decisions:
            ended_at = datetime.now(timezone.utc)
            return QAEvaluation(
                evaluator_name=self.name,
                status=EvaluationStatus.SKIPPED,
                score=1.0,
                findings=(),
                started_at=started_at,
                ended_at=ended_at,
                latency_ms=(ended_at - started_at).total_seconds() * 1000.0,
            )

        findings: list[RuntimeFinding] = []
        ordinal = 0
        non_allow = 0
        for decision in view.governance_decisions:
            if decision.is_allow:
                continue
            non_allow += 1
            code_severity = _DECISION_CLASSIFICATION.get(decision.decision)
            if code_severity is None:
                # Unknown verdict — surface as GOVERNANCE_VIOLATION + MEDIUM
                # so it isn't silently dropped. The offending verdict
                # value is appended to the canonical unknown-prefix so
                # audit tools see *which* unknown verdict was emitted.
                code = (
                    f"{FindingCode.GOVERNANCE_UNKNOWN_PREFIX.value}."
                    f"{decision.decision}"
                )
                severity = FindingSeverity.MEDIUM
                category = FindingCategory.GOVERNANCE_VIOLATION
            else:
                code, severity = code_severity
                category = FindingCategory.GOVERNANCE_VIOLATION
            findings.append(
                _build_finding(
                    view=view,
                    decision=decision,
                    code=code,
                    severity=severity,
                    category=category,
                    evaluator_name=self.name,
                    ordinal=ordinal,
                )
            )
            ordinal += 1

        ended_at = datetime.now(timezone.utc)
        latency_ms = (ended_at - started_at).total_seconds() * 1000.0
        total = len(view.governance_decisions)
        if non_allow == 0:
            status = EvaluationStatus.PASSED
            score = 1.0
        else:
            status = (
                EvaluationStatus.FAILED
                if non_allow == total
                else EvaluationStatus.WARNING
            )
            score = max(0.0, 1.0 - non_allow / total)

        return QAEvaluation(
            evaluator_name=self.name,
            status=status,
            score=score,
            findings=tuple(findings),
            started_at=started_at,
            ended_at=ended_at,
            latency_ms=latency_ms,
            metadata={
                "total_decisions": total,
                "non_allow": non_allow,
            },
        )


def _build_finding(
    *,
    view: InspectionView,
    decision: GovernanceDecisionView,
    code: str,
    severity: FindingSeverity,
    category: FindingCategory,
    evaluator_name: str,
    ordinal: int,
) -> RuntimeFinding:
    return RuntimeFinding(
        finding_id=derive_finding_id(
            execution_id=view.execution_id,
            evaluator_name=evaluator_name,
            code=code,
            ordinal=ordinal,
        ),
        evaluator_name=evaluator_name,
        category=category,
        severity=severity,
        code=code,
        message=(
            f"governance verdict {decision.decision!r} at stage "
            f"{decision.stage!r}: {decision.reason or 'no reason recorded'}"
        ),
        evidence=EvaluationEvidence(
            execution_id=view.execution_id,
            governance_decision_ids=(decision.decision_id,),
            metadata={
                EvidenceMetadataKey.POLICY_CHAIN_ID.value: decision.policy_chain_id,
                EvidenceMetadataKey.STAGE.value: decision.stage,
                EvidenceMetadataKey.VIOLATION_COUNT.value: decision.violation_count,
                EvidenceMetadataKey.DECISION.value: decision.decision,
            },
        ),
    )


__all__ = ["GovernanceComplianceEvaluator"]
