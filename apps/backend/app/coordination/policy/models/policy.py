"""`CoordinationPolicy` — a named, immutable bundle of rules.

A policy is a deployment-controlled descriptor: a stable id, a
human-readable name, a scope classification, and an ordered tuple
of `CoordinationPolicyRule`s.

Evaluators consume policies at composition time. A `TopologyEvaluator`
may be constructed with one or more policies whose rules constrain
the (sender, recipient) topology; an `EscalationEvaluator` may be
constructed with policies whose rules emit escalations; and so on.

The policy itself contains no executable code — it is pure
declarative configuration. This keeps replay semantics trivial
(same policies + same dispatch = same findings).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from app.coordination.policy.enums import CoordinationPolicyScope
from app.coordination.policy.identity import CoordinationPolicyId
from app.coordination.policy.models.rule import CoordinationPolicyRule


@dataclass(frozen=True, slots=True)
class CoordinationPolicy:
    """A named bundle of authorisation rules.

    Attributes:
        policy_id:    Stable identifier (typed `CoordinationPolicyId`).
        name:         Stable, human-readable name. Used in audit /
                      supervisor surfaces.
        scope:        The dimension this policy primarily scopes over.
                      (Individual rules may have narrower scopes.)
        rules:        Ordered tuple of rules. Order matters for
                      evaluators that short-circuit on first match;
                      it does not matter for evaluators that emit
                      one finding per matching rule.
        description:  Short human-readable description.
        metadata:     Free-form, propagated onto findings.
    """

    policy_id: CoordinationPolicyId
    name: str
    scope: CoordinationPolicyScope
    rules: tuple[CoordinationPolicyRule, ...]
    description: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_id": str(self.policy_id),
            "name": self.name,
            "scope": self.scope.value,
            "rules": [r.to_dict() for r in self.rules],
            "description": self.description,
            "metadata": dict(self.metadata),
        }


__all__ = ["CoordinationPolicy"]
