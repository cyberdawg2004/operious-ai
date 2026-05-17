"""Tool-invocation hygiene evaluator.

Inspects every tool invocation recorded under the execution. Findings:

* `tool.denied`  — invocation status == DENIED       (MEDIUM)
* `tool.failed`  — invocation status == FAILED        (MEDIUM)

A DENIED invocation typically pairs with a governance decision id
referenced from the invocation's evidence — the governance evaluator
inspects the governance side of the story separately.

SKIPS when the view has zero tool invocations: this is the explicit
"not applicable" signal; the aggregator excludes SKIPPED evaluators
from score aggregation so a tool-free execution doesn't get
penalised.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import ClassVar

from app.agents.enums import ToolInvocationStatus
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
from app.supervisor.models.view import InspectionView
from app.supervisor.taxonomy import EvidenceMetadataKey, FindingCode


class ToolInvocationEvaluator(BaseEvaluator):
    """Inspects tool-invocation outcomes for hygiene anomalies."""

    name: ClassVar[str] = "tool_invocation"

    async def evaluate(self, view: InspectionView) -> QAEvaluation:
        started_at = datetime.now(timezone.utc)

        if not view.tool_invocations:
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
        denied = 0
        failed = 0
        for inv in view.tool_invocations:
            if inv.status is ToolInvocationStatus.DENIED:
                denied += 1
                gov_ids = (
                    (inv.governance_decision_id,)
                    if inv.governance_decision_id is not None
                    else ()
                )
                findings.append(
                    RuntimeFinding(
                        finding_id=derive_finding_id(
                            execution_id=view.execution_id,
                            evaluator_name=self.name,
                            code=FindingCode.TOOL_DENIED.value,
                            ordinal=ordinal,
                        ),
                        evaluator_name=self.name,
                        category=FindingCategory.TOOL_INVOCATION_ANOMALY,
                        severity=FindingSeverity.MEDIUM,
                        code=FindingCode.TOOL_DENIED.value,
                        message=(
                            f"tool invocation denied: {inv.tool_name}: "
                            f"{inv.error or 'no reason recorded'}"
                        ),
                        evidence=EvaluationEvidence(
                            execution_id=view.execution_id,
                            tool_invocation_ids=(inv.invocation_id,),
                            governance_decision_ids=gov_ids,
                            metadata={
                                EvidenceMetadataKey.TOOL_NAME.value: inv.tool_name,
                            },
                        ),
                    )
                )
                ordinal += 1
            elif inv.status is ToolInvocationStatus.FAILED:
                failed += 1
                findings.append(
                    RuntimeFinding(
                        finding_id=derive_finding_id(
                            execution_id=view.execution_id,
                            evaluator_name=self.name,
                            code=FindingCode.TOOL_FAILED.value,
                            ordinal=ordinal,
                        ),
                        evaluator_name=self.name,
                        category=FindingCategory.TOOL_INVOCATION_ANOMALY,
                        severity=FindingSeverity.MEDIUM,
                        code=FindingCode.TOOL_FAILED.value,
                        message=(
                            f"tool invocation failed: {inv.tool_name}: "
                            f"{inv.error or 'no error recorded'}"
                        ),
                        evidence=EvaluationEvidence(
                            execution_id=view.execution_id,
                            tool_invocation_ids=(inv.invocation_id,),
                            metadata={
                                EvidenceMetadataKey.TOOL_NAME.value: inv.tool_name,
                            },
                        ),
                    )
                )
                ordinal += 1

        ended_at = datetime.now(timezone.utc)
        latency_ms = (ended_at - started_at).total_seconds() * 1000.0
        total = len(view.tool_invocations)
        anomalous = denied + failed
        if anomalous == 0:
            status = EvaluationStatus.PASSED
            score = 1.0
        else:
            status = (
                EvaluationStatus.FAILED
                if anomalous == total
                else EvaluationStatus.WARNING
            )
            score = max(0.0, 1.0 - anomalous / total)

        return QAEvaluation(
            evaluator_name=self.name,
            status=status,
            score=score,
            findings=tuple(findings),
            started_at=started_at,
            ended_at=ended_at,
            latency_ms=latency_ms,
            metadata={
                "total_invocations": total,
                "denied": denied,
                "failed": failed,
            },
        )


__all__ = ["ToolInvocationEvaluator"]
