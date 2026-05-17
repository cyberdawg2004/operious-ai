"""Supervisor contracts — typed entry / exit shapes.

* `requests`     — `ExecutionInspectionRequest`.
* `evaluations`  — `QAEvaluation`.
* `decisions`    — `SupervisorDecision`, `EscalationDecision`,
                    and the pure aggregator `build_supervisor_decision`.
* `results`      — `ExecutionInspectionResult` (apex output).
"""

from app.supervisor.contracts.decisions import (
    EscalationDecision,
    SupervisorDecision,
    build_supervisor_decision,
)
from app.supervisor.contracts.evaluations import QAEvaluation
from app.supervisor.contracts.requests import ExecutionInspectionRequest
from app.supervisor.contracts.results import ExecutionInspectionResult

__all__ = [
    "ExecutionInspectionRequest",
    "QAEvaluation",
    "EscalationDecision",
    "SupervisorDecision",
    "build_supervisor_decision",
    "ExecutionInspectionResult",
]
