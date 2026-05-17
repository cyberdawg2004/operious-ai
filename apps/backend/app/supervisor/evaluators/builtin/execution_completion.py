"""Execution-completion evaluator.

Inspects the execution's terminal state and runtime error string.

Findings:

* `execution.failed`     — final_state == FAILED        (HIGH)
* `execution.cancelled`  — final_state == CANCELLED with error  (MEDIUM)
* `execution.incomplete` — final_state is non-terminal           (HIGH;
                            should be impossible from the runtime
                            but the supervisor never trusts upstream
                            invariants)

A clean `COMPLETED` execution produces zero findings, status PASSED,
score 1.0.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import ClassVar

from app.agents.enums import ExecutionState
from app.agents.state_machine import is_terminal
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
from app.supervisor.taxonomy import FindingCode


class ExecutionCompletionEvaluator(BaseEvaluator):
    """Inspects terminal-state correctness for one execution."""

    name: ClassVar[str] = "execution_completion"

    async def evaluate(self, view: InspectionView) -> QAEvaluation:
        started_at = datetime.now(timezone.utc)
        findings: list[RuntimeFinding] = []
        ordinal = 0

        if view.final_state is ExecutionState.FAILED:
            findings.append(
                RuntimeFinding(
                    finding_id=derive_finding_id(
                        execution_id=view.execution_id,
                        evaluator_name=self.name,
                        code=FindingCode.EXECUTION_FAILED.value,
                        ordinal=ordinal,
                    ),
                    evaluator_name=self.name,
                    category=FindingCategory.EXECUTION_FAILURE,
                    severity=FindingSeverity.HIGH,
                    code=FindingCode.EXECUTION_FAILED.value,
                    message=(
                        view.error
                        or "execution terminated in FAILED state without an "
                        "attached error string"
                    ),
                    evidence=EvaluationEvidence(execution_id=view.execution_id),
                )
            )
            ordinal += 1
        elif view.final_state is ExecutionState.CANCELLED and view.error:
            findings.append(
                RuntimeFinding(
                    finding_id=derive_finding_id(
                        execution_id=view.execution_id,
                        evaluator_name=self.name,
                        code=FindingCode.EXECUTION_CANCELLED.value,
                        ordinal=ordinal,
                    ),
                    evaluator_name=self.name,
                    category=FindingCategory.EXECUTION_FAILURE,
                    severity=FindingSeverity.MEDIUM,
                    code=FindingCode.EXECUTION_CANCELLED.value,
                    message=f"execution cancelled with error: {view.error}",
                    evidence=EvaluationEvidence(execution_id=view.execution_id),
                )
            )
            ordinal += 1
        elif not is_terminal(view.final_state):
            findings.append(
                RuntimeFinding(
                    finding_id=derive_finding_id(
                        execution_id=view.execution_id,
                        evaluator_name=self.name,
                        code=FindingCode.EXECUTION_INCOMPLETE.value,
                        ordinal=ordinal,
                    ),
                    evaluator_name=self.name,
                    category=FindingCategory.EXECUTION_FAILURE,
                    severity=FindingSeverity.HIGH,
                    code=FindingCode.EXECUTION_INCOMPLETE.value,
                    message=(
                        f"execution reported non-terminal final_state "
                        f"{view.final_state.value!r}"
                    ),
                    evidence=EvaluationEvidence(execution_id=view.execution_id),
                )
            )
            ordinal += 1

        ended_at = datetime.now(timezone.utc)
        latency_ms = (ended_at - started_at).total_seconds() * 1000.0
        status = (
            EvaluationStatus.PASSED
            if not findings
            else EvaluationStatus.FAILED
        )
        score = 1.0 if not findings else 0.0

        return QAEvaluation(
            evaluator_name=self.name,
            status=status,
            score=score,
            findings=tuple(findings),
            started_at=started_at,
            ended_at=ended_at,
            latency_ms=latency_ms,
        )


__all__ = ["ExecutionCompletionEvaluator"]
