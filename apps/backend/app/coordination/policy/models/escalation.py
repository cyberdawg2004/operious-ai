"""`CoordinationPolicyEscalation` — typed, immutable escalation demand.

An escalation is the advisory artefact an `ESCALATE` finding attaches
to flag that the dispatch is conditional on an out-of-band review.
Policy NEVER invokes the escalation pathway — it merely records the
requirement on the persisted evaluation envelope.

Shape mirrors `CoordinationPolicyRestriction` discipline but uses
the escalation vocabulary. Escalation kinds and restriction kinds
are deliberately distinct concepts; a restriction degrades a
proceeding dispatch, while an escalation blocks it pending review.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.coordination.policy.enums import CoordinationEscalationType


@dataclass(frozen=True, slots=True)
class CoordinationPolicyEscalation:
    """One advisory escalation requirement attached to an `ESCALATE` finding.

    Attributes:
        kind:        Typed escalation kind from
                     `CoordinationEscalationType`.
        target:      Stable string naming the escalation target
                     (e.g. ``"approver:tenant:acme:owner"``,
                     ``"on_call:platform"``). Free-form vocabulary
                     the deployment controls.
        reason:      Short human-readable explanation. Surfaces in
                     audit + supervisor consumption.
        policy_id:   Stringified UUID of the originating policy (when
                     known).
        rule_id:     Stable rule id within the policy (when known).
        metadata:    Free-form, propagated through persistence.
    """

    kind: CoordinationEscalationType
    target: str = ""
    reason: str = ""
    policy_id: str | None = None
    rule_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict[str, Any])

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "target": self.target,
            "reason": self.reason,
            "policy_id": self.policy_id,
            "rule_id": self.rule_id,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(
        cls, data: dict[str, Any]
    ) -> "CoordinationPolicyEscalation":
        return cls(
            kind=CoordinationEscalationType(data["kind"]),
            target=str(data.get("target", "")),
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


__all__ = ["CoordinationPolicyEscalation"]
