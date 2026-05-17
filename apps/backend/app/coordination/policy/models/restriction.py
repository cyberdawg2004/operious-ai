"""`CoordinationPolicyRestriction` — typed, immutable restriction handle.

A restriction is the *advisory artefact* a `RESTRICT` (or, in some
edge cases, `ANNOTATE`) decision attaches to a finding. The
coordination substrate records restrictions but does NOT enforce
delivery semantics — that is the orchestration layer's job. Policy
must NEVER mutate orchestration behaviour (Rule 3).

Shape mirrors `app.governance.value_objects.RuntimeRestriction` in
discipline but uses the topology-restriction vocabulary
(`CoordinationRestrictionType`). The two enums are deliberately
distinct — substrate isolation requires that topology restrictions
not be confused with governance restrictions in the audit trail.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from app.coordination.policy.enums import CoordinationRestrictionType


@dataclass(frozen=True, slots=True)
class CoordinationPolicyRestriction:
    """One advisory restriction attached to a `RESTRICT` finding.

    Attributes:
        kind:        Typed restriction kind from
                     `CoordinationRestrictionType`.
        target:      Stable string naming what is restricted (sender
                     id, recipient id, direction value, message type
                     value, tenant id, etc.).
        value:       Optional structured payload describing the
                     restriction (e.g. ``{"cap": 10}`` for a priority
                     cap, ``{"redact": ["pii.*"]}`` for redaction).
                     Must be JSON-coercible.
        reason:      Short human-readable reason. Surfaces in audit
                     trails.
        policy_id:   Stringified UUID of the originating policy (when
                     known). Optional — external evaluators may emit
                     restrictions without an explicit policy
                     identifier.
        rule_id:     Stable rule id within the policy (when known).
        metadata:    Free-form, propagated through persistence.
    """

    kind: CoordinationRestrictionType
    target: str
    value: Mapping[str, Any] = field(default_factory=dict)
    reason: str = ""
    policy_id: str | None = None
    rule_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "target": self.target,
            "value": dict(self.value),
            "reason": self.reason,
            "policy_id": self.policy_id,
            "rule_id": self.rule_id,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(
        cls, data: Mapping[str, Any]
    ) -> "CoordinationPolicyRestriction":
        return cls(
            kind=CoordinationRestrictionType(data["kind"]),
            target=str(data["target"]),
            value=dict(data.get("value") or {}),
            reason=str(data.get("reason", "")),
            policy_id=(
                str(data["policy_id"])
                if data.get("policy_id") is not None
                else None
            ),
            rule_id=(
                str(data["rule_id"])
                if data.get("rule_id") is not None
                else None
            ),
            metadata=dict(data.get("metadata") or {}),
        )


__all__ = ["CoordinationPolicyRestriction"]
