"""`ArbitrationRecommendation` — one input recommendation.

A recommendation is distinct from a signal:

* a **signal** asserts a verdict (ALLOW / DENY / PASS / FAIL / …),
* a **recommendation** asserts a directive (a free-form string,
  e.g. ``escalate_to:supervisor:platform``, ``degrade:warn``,
  ``retry``).

Supervisors are the canonical source of recommendations. They are
**read-only evaluators** by the platform's architectural contract;
their directives are advisory inputs to arbitration, not commands
to be executed. The arbitration substrate NEVER acts on a
recommendation — it only INTERPRETS contradictions between
recommendations.

Two recommendations conflict when their `directive`s are
non-equal (an arbitrary-string equality check — the substrate does
not parse the directive). The arbitration evaluators surface the
disagreement as inspectable state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.arbitration.enums import ArbitrationAuthorityLevel
from app.arbitration.identity import ArbitrationRecommendationId


@dataclass(frozen=True, slots=True)
class ArbitrationRecommendation:
    """One advisory directive submitted to the case.

    Attributes:
        recommendation_id: Stable identifier.
        authority:         Authority of the recommending source.
        directive:         Free-form directive string. The substrate
                            treats this as opaque text for equality
                            checking and audit; it never executes
                            the directive.
        source_substrate:  Short string naming the recommender's
                            substrate (typically ``supervisor`` or
                            ``governance``).
        source_id:         Stable identifier within the recommender.
        reason:            Short human-readable rationale.
        emitted_at:        Wall-clock timestamp from the recommender.
        metadata:          Free-form, propagated through persistence.
    """

    recommendation_id: ArbitrationRecommendationId
    authority: ArbitrationAuthorityLevel
    directive: str
    source_substrate: str
    source_id: str
    reason: str = ""
    emitted_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict[str, Any])


__all__ = ["ArbitrationRecommendation"]
