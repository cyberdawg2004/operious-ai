"""Approved communication-pattern value objects.

CRITICAL discipline:

Communication patterns are **retrieved**, not invented. Only
APPROVED patterns participate in retrieval. The pattern's
`approval_id` makes the approval ancestry explicit; the
substrate refuses to register a pattern without one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from app.organizational_intelligence.enums import (
    CommunicationPatternKind,
    IntelligenceScope,
    TonalityClass,
)
from app.organizational_intelligence.identity import (
    ApprovalId,
    CommunicationPatternId,
)


@dataclass(frozen=True, slots=True)
class CommunicationPattern:
    """An immutable APPROVED communication pattern.

    Attributes:
        pattern_id:           Stable identifier.
        tenant_id:            Tenant scope; ``None`` for substrate-
                               wide patterns.
        scope:                Authority-scope classification.
        kind:                 Coarse pattern classification.
        handle:               Caller-supplied stable handle (e.g.
                               ``"de_escalation.calm.v1"``).
        body:                 Canonical body text.
        applicable_classes:   Tonality classes the pattern is
                               appropriate for (sorted on construction).
        approval_id:          The approval record that promoted
                               this pattern. **Required**.
        registered_at:        UTC timestamp of substrate
                               registration.
        author_handle:        Free-form attribution.
        metadata:             Free-form audit metadata.

    Raises:
        ValueError: when ``approval_id`` is missing or fields are
            empty.
    """

    pattern_id: CommunicationPatternId
    tenant_id: str | None
    scope: IntelligenceScope
    kind: CommunicationPatternKind
    handle: str
    body: str
    applicable_classes: tuple[TonalityClass, ...]
    approval_id: ApprovalId
    registered_at: datetime
    author_handle: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.handle:
            raise ValueError(
                "CommunicationPattern.handle must be non-empty"
            )
        if not self.body:
            raise ValueError(
                "CommunicationPattern.body must be non-empty"
            )
        if self.registered_at.tzinfo is None:
            raise ValueError(
                "CommunicationPattern.registered_at must be tz-aware"
            )
        if not self.applicable_classes:
            raise ValueError(
                "CommunicationPattern.applicable_classes must be "
                "non-empty"
            )


@dataclass(frozen=True, slots=True)
class CommunicationRetrievalCandidate:
    """One match returned from a retrieval call.

    The score is **deterministic** — derived from a pinned
    matching algorithm, never from random sampling or LLM scoring.
    """

    pattern: CommunicationPattern
    score: float
    match_reason: str

    def __post_init__(self) -> None:
        if not 0.0 <= self.score <= 1.0:
            raise ValueError(
                "CommunicationRetrievalCandidate.score must be in "
                "[0.0, 1.0]"
            )


__all__ = [
    "CommunicationPattern",
    "CommunicationRetrievalCandidate",
]
