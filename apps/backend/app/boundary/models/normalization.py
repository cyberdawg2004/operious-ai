"""`BoundaryNormalizationResult` — output of one adapter pass.

Carries the canonical fields the substrate extracted from a raw
ingress payload, the classification status, and an optional error
description. Adapters return this shape from `normalize()`; the
substrate trusts it and does not re-validate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from app.boundary.enums import (
    BoundaryMessageType,
    BoundaryNormalizationStatus,
)


@dataclass(frozen=True, slots=True)
class BoundaryNormalizationResult:
    """Output of an ingress adapter's normalisation pass.

    Attributes:
        status:                  Outcome classification.
        message_type:            Canonical message-type
                                  classification (UNKNOWN if the
                                  adapter could not classify).
        external_message_id:     Stable id within the external
                                  system. Required when status is
                                  OK; may be ``None`` when status
                                  indicates failure.
        external_conversation_id: Stable conversation id within
                                  the external system.
        external_emitted_at:     Wall-clock timestamp the external
                                  system reported the event.
                                  ``None`` when not provided.
        canonical_payload:       Normalised payload — a
                                  canonical-ordered dict of
                                  primitive values + nested
                                  dicts/lists. Used as the basis
                                  for replay-drift detection.
        error:                   Short human-readable description
                                  when status != OK.
        metadata:                Free-form per-adapter audit
                                  payload (e.g. signature
                                  validation flags).
    """

    status: BoundaryNormalizationStatus
    message_type: BoundaryMessageType = BoundaryMessageType.UNKNOWN
    external_message_id: str | None = None
    external_conversation_id: str | None = None
    external_emitted_at: datetime | None = None
    canonical_payload: Mapping[str, Any] = field(default_factory=dict)
    error: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def is_ok(self) -> bool:
        return self.status is BoundaryNormalizationStatus.OK


__all__ = ["BoundaryNormalizationResult"]
