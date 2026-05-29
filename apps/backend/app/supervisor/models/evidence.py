"""Evaluation evidence — pointers to the runtime artifacts a finding
references.

A `RuntimeFinding` carries one `EvaluationEvidence` so replay tools
and audit queries can reconstruct *what* in the execution backed the
finding. Evidence is purely referential — it holds identifiers, never
the full payloads. The payloads live in the persistence layer of the
respective subsystem (agents / governance / tools).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class EvaluationEvidence:
    """Pure-reference pointers backing one finding.

    Attributes:
        execution_id:             The execution under inspection.
        tool_invocation_ids:      Tool invocations the finding implicates.
        governance_decision_ids:  Governance decisions the finding
                                  implicates (DENY-decision references,
                                  policy violations, etc.).
        state_transition_indices: Indices into the inspection view's
                                  state-transition tuple. Index-based
                                  rather than transition-copy so the
                                  evidence stays small.
        metadata:                 Free-form structured context.
    """

    execution_id: uuid.UUID
    tool_invocation_ids: tuple[uuid.UUID, ...] = ()
    governance_decision_ids: tuple[uuid.UUID, ...] = ()
    state_transition_indices: tuple[int, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict[str, Any])


__all__ = ["EvaluationEvidence"]
