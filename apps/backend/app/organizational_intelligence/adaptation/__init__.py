"""Adaptation discipline markers.

This module is **deliberately small**. Adaptation is, by Sprint
O's central rule, NEVER a runtime activity. Every change to
operational behaviour flows through:

    interaction
        → supervision
        → evaluation
        → approval
        → indexing
        → future retrieval

The only thing this module exposes is a frozen mapping from
"adaptation event kind" → "what runtime call records it" so the
discipline is visible in code, not just documentation.
"""

from __future__ import annotations

from app.organizational_intelligence.enums import (
    IntelligenceTraceKind,
    MemoryArtifactStatus,
)


# Frozen catalogue: which runtime trace KINDS produce adaptation
# events. Anything not in this catalogue is, by construction, not
# adaptation — and the substrate forbids it from changing
# retrieval eligibility.
ADAPTATION_TRACE_KINDS: frozenset[IntelligenceTraceKind] = (
    frozenset(
        {
            IntelligenceTraceKind.MEMORY_APPROVE,
            IntelligenceTraceKind.MEMORY_REJECT,
            IntelligenceTraceKind.MEMORY_SUPERSEDE,
            IntelligenceTraceKind.MEMORY_RETIRE,
            IntelligenceTraceKind.COMMUNICATION_REGISTER,
            IntelligenceTraceKind.RECOMMENDATION_REVIEW,
        }
    )
)


# Frozen status set considered "active operational adoption" —
# the substrate ONLY treats artifacts in these statuses as
# eligible to inform retrieval / recommendation.
ACTIVE_ADOPTION_STATUSES: frozenset[MemoryArtifactStatus] = (
    frozenset(
        {
            MemoryArtifactStatus.APPROVED,
        }
    )
)


def is_adaptation_event(kind: IntelligenceTraceKind) -> bool:
    """True iff the trace kind represents a governed-adoption event."""
    return kind in ADAPTATION_TRACE_KINDS


def is_active_adoption(status: MemoryArtifactStatus) -> bool:
    """True iff the status represents active operational adoption."""
    return status in ACTIVE_ADOPTION_STATUSES


__all__ = [
    "ACTIVE_ADOPTION_STATUSES",
    "ADAPTATION_TRACE_KINDS",
    "is_active_adoption",
    "is_adaptation_event",
]
