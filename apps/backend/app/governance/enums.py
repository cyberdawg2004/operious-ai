"""Governance enums — the entire vocabulary of typed verdicts and stages.

These enums are the **single source of truth** for governance
semantics. Every decision, every stage, every restriction kind, every
severity is expressed through one of these enum values. Naked strings
do not cross governance boundaries.

The `StrEnum` choice gives us JSON-serialisable values for free —
necessary for replay envelopes and audit records — while still keeping
the type checker honest at call sites.
"""

from __future__ import annotations

from enum import IntEnum, StrEnum


class Decision(StrEnum):
    """The apex verdict any governance evaluation can produce.

    Ordering by *restrictiveness* is encoded in `Decision.precedence()`.
    Most-restrictive wins when a chain produces multiple verdicts.
    """

    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"
    ESCALATE = "escalate"
    DEGRADE = "degrade"
    REDACT = "redact"
    ALLOW = "allow"

    @classmethod
    def precedence(cls, decision: "Decision") -> int:
        """Return an integer score; lower number = more restrictive.

        The engine uses `min(precedence(d) for d in decisions)` to
        collapse N rule verdicts into one decision. The mapping below
        is the **only** place precedence is encoded — every other
        layer reads it from here.
        """
        return _PRECEDENCE[decision]


_PRECEDENCE: dict[Decision, int] = {
    Decision.DENY: 0,
    Decision.REQUIRE_APPROVAL: 1,
    Decision.ESCALATE: 2,
    Decision.DEGRADE: 3,
    Decision.REDACT: 4,
    Decision.ALLOW: 5,
}


class EnforcementStage(StrEnum):
    """The runtime stage a governance evaluation pertains to.

    The vocabulary covers every integration seam Sprint I+ may need to
    enforce against. Not every stage is wired today (Sprint I ships
    PRE/POST around context assembly); the rest are first-class values
    so future sprints add hooks without touching the substrate.
    """

    PRE_REQUEST = "pre_request"
    PRE_RETRIEVAL = "pre_retrieval"
    POST_RETRIEVAL = "post_retrieval"
    PRE_GROUNDING = "pre_grounding"
    PRE_EXECUTION = "pre_execution"
    POST_EXECUTION = "post_execution"


class ViolationSeverity(IntEnum):
    """Operational severity attached to a single rule violation.

    Severity is independent of `Decision`: a DENY can be LOW (procedural
    block) and a REDACT can be HIGH (sensitive-content removal).
    Severity feeds dashboards / alerting; `Decision` feeds runtime
    enforcement.
    """

    LOW = 10
    MEDIUM = 20
    HIGH = 30
    CRITICAL = 40


class RestrictionKind(StrEnum):
    """Vocabulary of ongoing runtime restrictions that decisions emit.

    A `DEGRADE` decision typically attaches one or more restrictions —
    e.g., "use model X" or "cap chunk count at N". The kinds here are
    extensible; future sprints add values as new restriction shapes
    are needed. Downstream consumers MUST treat an unknown kind as
    fail-safe (deny / log).
    """

    MODEL_RESTRICTION = "model_restriction"
    SOURCE_RESTRICTION = "source_restriction"
    CHUNK_CAP = "chunk_cap"
    TOKEN_CAP = "token_cap"
    CONTENT_REDACTION = "content_redaction"
    RATE_LIMIT = "rate_limit"
    CAPABILITY_RESTRICTION = "capability_restriction"


__all__ = [
    "Decision",
    "EnforcementStage",
    "ViolationSeverity",
    "RestrictionKind",
]
