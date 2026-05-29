"""`ResolutionAuthority` — the substrate-named prevailing authority.

When the runtime resolves a case, it identifies WHICH authority
prevailed (and WHICH source within that authority). The
`ResolutionAuthority` value object pairs the abstract level with
the concrete source identifier so the audit trail records both.

A non-resolution outcome (INCONCLUSIVE / CONFLICT / DEADLOCK /
ERROR) has no prevailing authority; in those cases the apex
decision's `prevailing_authority` is ``None``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.arbitration.enums import ArbitrationAuthorityLevel


@dataclass(frozen=True, slots=True)
class ResolutionAuthority:
    """The substrate-named prevailing authority for one resolution.

    Attributes:
        level:            Authority level that prevailed.
        source_substrate: Short string naming the prevailing
                           substrate.
        source_id:        Stable identifier within that substrate.
        verdict:          The prevailing verdict (free-form string;
                           caller-stable). The substrate does not
                           re-classify it.
        reason:           Short human-readable rationale.
        metadata:         Free-form, propagated through persistence.
    """

    level: ArbitrationAuthorityLevel
    source_substrate: str
    source_id: str
    verdict: str
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict[str, Any])


__all__ = ["ResolutionAuthority"]
