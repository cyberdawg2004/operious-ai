"""`QAEvaluation` — one evaluator's verdict for one inspection.

Carries the evaluator's status, score, emitted findings, and timing.
The supervisor's apex decision aggregator (`build_supervisor_decision`)
consumes a sequence of these.

`score` is a free-form scalar in [0.0, 1.0]:
  - 1.0 = best (no concerns from this evaluator),
  - 0.0 = worst (severe concerns).
The supervisor does not interpret scores; aggregation uses them as
weighted opaque ordering keys.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from app.supervisor.enums import EvaluationStatus
from app.supervisor.models.findings import RuntimeFinding


@dataclass(frozen=True, slots=True)
class QAEvaluation:
    """One evaluator's verdict over one `InspectionView`."""

    evaluator_name: str
    status: EvaluationStatus
    score: float
    findings: tuple[RuntimeFinding, ...]
    started_at: datetime
    ended_at: datetime
    latency_ms: float
    error: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


__all__ = ["QAEvaluation"]
