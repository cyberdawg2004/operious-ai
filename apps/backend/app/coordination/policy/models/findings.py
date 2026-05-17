"""`CoordinationPolicyFinding` — one topology-authorisation observation.

A finding is the atomic unit of policy output. An evaluator emits
zero or more findings per request; the runtime aggregates findings
across the evaluator chain into one apex
`CoordinationPolicyEvaluationResult`.

Findings are deliberately rich:

* `decision`     — the verdict this finding carries.
* `scope`        — which axis the finding observes.
* `code`         — stable code from
                    `CoordinationPolicyFindingCode` (or external
                    deployment-specific code).
* `policy_id`    — link back to the originating policy (when known).
* `rule_id`      — link back to the originating rule (when known).
* `restrictions` / `escalations`
                  — advisory artefacts attached to the finding.

The rich shape lets supervisor / audit consumers reconstruct the
full topology-decision lineage from persisted findings without
re-running evaluators.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from app.coordination.policy.enums import (
    CoordinationPolicyDecision,
    CoordinationPolicyScope,
)
from app.coordination.policy.models.escalation import (
    CoordinationPolicyEscalation,
)
from app.coordination.policy.models.restriction import (
    CoordinationPolicyRestriction,
)


@dataclass(frozen=True, slots=True)
class CoordinationPolicyFinding:
    """One topology-authorisation finding.

    Attributes:
        finding_id:     Stable UUID. Derived via
                         `derive_finding_id` for replay-safety.
        evaluator_name: Stable name of the emitting evaluator.
        scope:          Which axis the finding observes.
        decision:       Verdict carried by this finding.
        code:           Stable code (typically from
                         `CoordinationPolicyFindingCode`).
        message:        Short human-readable description.
        policy_id:      Originating policy (when known).
        rule_id:        Originating rule (when known).
        restrictions:   Advisory restrictions attached.
        escalations:    Advisory escalations attached.
        detected_at:    Wall-clock timestamp (UTC).
        metadata:       Free-form, propagated through persistence.
    """

    finding_id: uuid.UUID
    evaluator_name: str
    scope: CoordinationPolicyScope
    decision: CoordinationPolicyDecision
    code: str
    message: str
    policy_id: str | None = None
    rule_id: str | None = None
    restrictions: tuple[CoordinationPolicyRestriction, ...] = ()
    escalations: tuple[CoordinationPolicyEscalation, ...] = ()
    detected_at: datetime | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


__all__ = ["CoordinationPolicyFinding"]
