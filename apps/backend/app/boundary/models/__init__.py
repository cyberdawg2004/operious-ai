"""Boundary substrate value-object models.

All shapes are frozen, slotted, replay-safe value objects.
Storage serialisation lives under `app/boundary/persistence/`.
"""

from app.boundary.models.event import ExternalBoundaryEvent
from app.boundary.models.normalization import (
    BoundaryNormalizationResult,
)
from app.boundary.models.payload import (
    EgressPayload,
    IngressPayload,
)
from app.boundary.models.replay import BoundaryReplayRecord
from app.boundary.models.source import BoundarySource

__all__ = [
    "BoundaryNormalizationResult",
    "BoundaryReplayRecord",
    "BoundarySource",
    "EgressPayload",
    "ExternalBoundaryEvent",
    "IngressPayload",
]
