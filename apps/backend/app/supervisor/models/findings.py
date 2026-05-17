"""Findings + anomalies.

`RuntimeFinding` is the atom every evaluator emits. `ExecutionAnomaly`
is an optional higher-level reification used by builtin evaluators
when a finding pattern is stable enough to be discussed by name (e.g.
"illegal_state_transition", "governance_deny_in_tool_invocation").

Both are `frozen=True, slots=True` — replay-safe by construction.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

from app.supervisor.enums import FindingCategory, FindingSeverity
from app.supervisor.models.evidence import EvaluationEvidence


@dataclass(frozen=True, slots=True)
class RuntimeFinding:
    """One atomic observation produced by an evaluator.

    `code` is a short, stable identifier (`"execution.failed"`,
    `"tool.denied"`); it is the queryable key downstream consumers
    branch on. `message` is human-readable diagnostic text — never
    parsed by code.

    `finding_id` is normally derived via `identity.derive_finding_id`
    so replays produce byte-identical ids; callers may also pass an
    explicit id for testing.
    """

    finding_id: uuid.UUID
    evaluator_name: str
    category: FindingCategory
    severity: FindingSeverity
    code: str
    message: str
    evidence: EvaluationEvidence
    detected_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ExecutionAnomaly:
    """A named, stable anomaly type — a higher-level shape over findings.

    Useful when a supervisor evaluator wants to surface a named class
    of issue (`"governance_bypass_attempt"`) in addition to (or instead
    of) raw findings. Sprint K ships the type and the discipline; the
    builtin evaluators use it sparingly.
    """

    anomaly_id: uuid.UUID
    code: str
    severity: FindingSeverity
    evidence: EvaluationEvidence
    description: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)


__all__ = ["RuntimeFinding", "ExecutionAnomaly"]
