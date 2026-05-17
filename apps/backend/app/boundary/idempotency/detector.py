"""`BoundaryReplayDetector` — pure replay classification.

Single deterministic decision function. Given:

* a freshly derived `replay_key`,
* a `content_fingerprint` of the canonical payload,
* the registry,

the detector decides whether this delivery is NEW,
REPLAY_OF_KNOWN, or LINEAGE_DRIFT — without itself mutating the
registry. The runtime calls the detector first, then the registry
APIs accordingly. This split keeps the decision function pure and
testable.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.boundary.enums import BoundaryReplayDisposition
from app.boundary.identity import BoundaryEventId
from app.boundary.idempotency.registry import (
    BoundaryIdempotencyRegistry,
)


@dataclass(frozen=True, slots=True)
class BoundaryReplayDecision:
    """Pure result of one replay classification.

    Attributes:
        disposition:        One of NEW / REPLAY_OF_KNOWN /
                             LINEAGE_DRIFT / INVALID_KEY.
        replay_key:         The deterministic replay key. ``None``
                             when disposition is INVALID_KEY.
        original_event_id:  Set for replay/drift; equals the
                             registry's stored event_id. ``None``
                             for NEW / INVALID_KEY.
    """

    disposition: BoundaryReplayDisposition
    replay_key: uuid.UUID | None
    original_event_id: BoundaryEventId | None = None


class BoundaryReplayDetector:
    """Stateless replay classifier."""

    __slots__ = ()

    async def classify(
        self,
        *,
        replay_key: uuid.UUID | None,
        content_fingerprint: str,
        registry: BoundaryIdempotencyRegistry,
    ) -> BoundaryReplayDecision:
        """Classify one inbound delivery."""
        if replay_key is None:
            return BoundaryReplayDecision(
                disposition=BoundaryReplayDisposition.INVALID_KEY,
                replay_key=None,
                original_event_id=None,
            )

        existing = await registry.get(replay_key)
        if existing is None:
            return BoundaryReplayDecision(
                disposition=BoundaryReplayDisposition.NEW,
                replay_key=replay_key,
                original_event_id=None,
            )

        if existing.content_fingerprint == content_fingerprint:
            return BoundaryReplayDecision(
                disposition=BoundaryReplayDisposition.REPLAY_OF_KNOWN,
                replay_key=replay_key,
                original_event_id=existing.event_id,
            )

        return BoundaryReplayDecision(
            disposition=BoundaryReplayDisposition.LINEAGE_DRIFT,
            replay_key=replay_key,
            original_event_id=existing.event_id,
        )


__all__ = [
    "BoundaryReplayDecision",
    "BoundaryReplayDetector",
]
