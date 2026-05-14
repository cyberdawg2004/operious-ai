"""Governance value objects.

Frozen, hashable, replay-friendly types that flow through the
governance pipeline alongside the apex `GovernanceDecision`.

* `PolicyViolation`    — one rule that produced a non-ALLOW verdict.
* `RuntimeRestriction` — an ongoing constraint attached to a decision
                         (typically by DEGRADE).

Both types carry the policy / rule identifiers that produced them so
supervisor runtimes can reconstruct *why* a restriction is in force.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from app.governance.enums import Decision, RestrictionKind, ViolationSeverity


@dataclass(frozen=True, slots=True)
class PolicyViolation:
    """Record of one rule whose verdict was anything other than ALLOW.

    `policy_name` + `rule_id` form the stable identity pair the audit
    pipeline correlates against governance configuration. `detail` is
    a short human-readable description; structured details live in
    `metadata`. Supervisor runtimes filter / group violations by
    `severity` independently from `decision`.
    """

    policy_name: str
    rule_id: str
    decision: Decision
    severity: ViolationSeverity
    detail: str
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RuntimeRestriction:
    """An ongoing constraint downstream consumers must honour.

    A restriction is the **operational artefact** of a decision —
    typically attached by DEGRADE ("use model X"), REDACT ("strip
    content matching pattern Y"), or DENY-with-fallback. Downstream
    consumers MUST treat an unknown `kind` as fail-safe (deny / log).

    Attributes:
        kind:       Restriction vocabulary (see `RestrictionKind`).
        target:     What the restriction applies to (e.g. "model",
                    "source:sops", "tenant:acme"). Stable, dotted /
                    colon-delimited string for grep-ability.
        value:      Constraint value. Type depends on `kind` — the
                    handler that consumes the restriction is
                    responsible for narrow typing.
        reason:     Human-readable explanation.
        policy_name: Producing policy (for audit).
        rule_id:    Producing rule (for audit).
        metadata:   Opaque structured payload.
    """

    kind: RestrictionKind
    target: str
    value: Any
    reason: str
    policy_name: str
    rule_id: str
    metadata: Mapping[str, Any] = field(default_factory=dict)


__all__ = ["PolicyViolation", "RuntimeRestriction"]
