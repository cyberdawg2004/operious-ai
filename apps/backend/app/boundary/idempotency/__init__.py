"""Boundary idempotency / replay-detection infrastructure.

* `BoundaryIdempotencyRegistry` — write-once-but-observable store
                                   of `BoundaryReplayRecord`s.
* `BoundaryReplayDetector`     — pure decision function: given a
                                   replay key + content fingerprint
                                   + the registry, classify the
                                   delivery as NEW / REPLAY_OF_KNOWN
                                   / LINEAGE_DRIFT.
* `BoundaryReplayDecision`     — result shape returned by the
                                   detector.

Sprint M discipline: this layer DETECTS replays. It does NOT
execute replays. Replay-execution is a future sprint.
"""

from app.boundary.idempotency.detector import (
    BoundaryReplayDecision,
    BoundaryReplayDetector,
)
from app.boundary.idempotency.registry import (
    BoundaryIdempotencyRegistry,
)

__all__ = [
    "BoundaryIdempotencyRegistry",
    "BoundaryReplayDecision",
    "BoundaryReplayDetector",
]
