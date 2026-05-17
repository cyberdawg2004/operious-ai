"""`CoordinationPolicyRule` — one declarative authorisation rule.

A rule expresses ONE topology-authorisation predicate. It pattern-
matches over the dispatch fields (sender, recipient, direction,
message type, tenant) and produces a verdict + optional restrictions
/ escalations.

Pattern matching:

* Pattern fields are glob-style strings (``"agent:*"`` matches any
  agent id; ``"agent:retriever"`` matches exactly).
* ``None`` on a pattern field means "do not constrain this axis".
* The runtime evaluates rules in declaration order; the first rule
  whose pattern matches contributes its verdict. Rules whose
  pattern does NOT match are silent (no finding).

The rule shape is deliberately declarative — evaluators interpret
the rule; the rule itself contains no executable code. Replays
reproduce the same verdicts byte-for-byte because the matching
function is pure.

Determinism: rule equality compares every field including ordered
restriction / escalation tuples. Two structurally-equal rules
produce structurally-equal findings.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from app.coordination.enums import (
    CoordinationDirection,
    CoordinationMessageType,
)
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
class CoordinationPolicyRule:
    """One declarative topology-authorisation rule.

    Attributes:
        rule_id:           Stable, deployment-pinned rule identifier.
                            Surfaces on every finding the rule emits.
        scope:             What dimension the rule scopes over. Used
                            by audit dashboards to group findings.
        decision:          The verdict this rule emits when its
                            pattern matches.
        description:       Short human-readable description.
        sender_pattern:    Glob over sender id (e.g. ``"agent:*"``).
                            ``None`` = unconstrained on this axis.
        recipient_pattern: Glob over recipient id.
        direction:         Optional direction the rule constrains.
                            ``None`` = unconstrained.
        message_type:      Optional message type the rule constrains.
        sender_tenant_pattern:
                            Glob over the sender's tenant id (when
                            the dispatch carries one).
        recipient_tenant_pattern:
                            Glob over the recipient's tenant id.
        restrictions:     Restrictions to attach when this rule fires
                            (typically for RESTRICT verdicts).
        escalations:      Escalations to attach when this rule fires
                            (typically for ESCALATE verdicts).
        metadata:          Free-form, propagated onto findings.
    """

    rule_id: str
    scope: CoordinationPolicyScope
    decision: CoordinationPolicyDecision
    description: str = ""
    sender_pattern: str | None = None
    recipient_pattern: str | None = None
    direction: CoordinationDirection | None = None
    message_type: CoordinationMessageType | None = None
    sender_tenant_pattern: str | None = None
    recipient_tenant_pattern: str | None = None
    restrictions: tuple[CoordinationPolicyRestriction, ...] = ()
    escalations: tuple[CoordinationPolicyEscalation, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "scope": self.scope.value,
            "decision": self.decision.value,
            "description": self.description,
            "sender_pattern": self.sender_pattern,
            "recipient_pattern": self.recipient_pattern,
            "direction": (
                self.direction.value if self.direction is not None else None
            ),
            "message_type": (
                self.message_type.value
                if self.message_type is not None
                else None
            ),
            "sender_tenant_pattern": self.sender_tenant_pattern,
            "recipient_tenant_pattern": self.recipient_tenant_pattern,
            "restrictions": [r.to_dict() for r in self.restrictions],
            "escalations": [e.to_dict() for e in self.escalations],
            "metadata": dict(self.metadata),
        }


__all__ = ["CoordinationPolicyRule"]
