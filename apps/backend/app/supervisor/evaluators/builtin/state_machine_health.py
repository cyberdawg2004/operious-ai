"""State-machine health evaluator.

Walks the recorded `state_transitions` on the inspection view and
validates each move against the canonical transition table in
`app.agents.state_machine`. Emits an `state_machine.illegal_transition`
finding (CRITICAL) for any move the table rejects.

A clean execution produces zero findings.

This evaluator is the supervisor's last line of defence against
substrate bugs — the runtime should never produce illegal transitions
because it gates them with `assert_transition`, but if a record was
hand-built (or storage was tampered with), this evaluator catches it
on replay.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import ClassVar

from app.agents.state_machine import can_transition
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


class StateMachineHealthEvaluator(BaseEvaluator):
    """Validates the execution's recorded state transitions."""

    name: ClassVar[str] = "state_machine_health"

    async def evaluate(self, view: InspectionView) -> QAEvaluation:
        started_at = datetime.now(timezone.utc)
        findings: list[RuntimeFinding] = []
        ordinal = 0

        for idx, transition in enumerate(view.state_transitions):
            if not can_transition(transition.from_state, transition.to_state):
                findings.append(
                    RuntimeFinding(
                        finding_id=derive_finding_id(
                            execution_id=view.execution_id,
                            evaluator_name=self.name,
                            code=FindingCode.STATE_MACHINE_ILLEGAL_TRANSITION.value,
                            ordinal=ordinal,
                        ),
                        evaluator_name=self.name,
                        category=FindingCategory.STATE_MACHINE_ANOMALY,
                        severity=FindingSeverity.CRITICAL,
                        code=FindingCode.STATE_MACHINE_ILLEGAL_TRANSITION.value,
                        message=(
                            f"illegal transition at index {idx}: "
                            f"{transition.from_state.value!r} -> "
                            f"{transition.to_state.value!r}"
                        ),
                        evidence=EvaluationEvidence(
                            execution_id=view.execution_id,
                            state_transition_indices=(idx,),
                        ),
                    )
                )
                ordinal += 1

        ended_at = datetime.now(timezone.utc)
        latency_ms = (ended_at - started_at).total_seconds() * 1000.0

        if not view.state_transitions:
            status = EvaluationStatus.SKIPPED
            score = 1.0
        elif not findings:
            status = EvaluationStatus.PASSED
            score = 1.0
        else:
            status = EvaluationStatus.FAILED
            score = 0.0

        return QAEvaluation(
            evaluator_name=self.name,
            status=status,
            score=score,
            findings=tuple(findings),
            started_at=started_at,
            ended_at=ended_at,
            latency_ms=latency_ms,
            metadata={
                "transition_count": len(view.state_transitions),
            },
        )


__all__ = ["StateMachineHealthEvaluator"]
