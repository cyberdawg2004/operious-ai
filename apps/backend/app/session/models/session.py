"""`OperationalSession` — apex continuity-identity record.

The `OperationalSession` is the substrate's identity-bearing
record: who/what the session is, when it opened, what its
current lifecycle classification is, and which lineage it sits
in. It deliberately does NOT carry the timeline events themselves
(those live in `SessionTimeline`) so identity reads can be cheap
and reconstruction can fetch the full timeline lazily.

Critical: `OperationalSession` is IMMUTABLE. A lifecycle
reclassification produces a NEW instance via the runtime —
it does not mutate the existing record.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.session.models.context import SessionContext
from app.session.models.identity import SessionIdentity
from app.session.models.lifecycle import SessionLifecycle
from app.session.models.lineage import SessionLineage


@dataclass(frozen=True, slots=True)
class OperationalSession:
    """Apex immutable continuity record.

    Attributes:
        identity:        Composite session identity.
        opened_at:       UTC timestamp the session was opened.
        lifecycle:       Current lifecycle classification.
        lineage:         Immutable ancestry record. ``None``
                          allowed only for transient lookups; the
                          runtime always populates it.
        context:         Continuity metadata. ``None`` until a
                          `record_context()` call binds it.
        sequence_head:   Sequence number of the latest timeline
                          event, or ``-1`` if no events yet.
        revision:        Monotonic write-counter incremented on
                          each lifecycle/context/lineage update.
                          Used purely for optimistic-concurrency
                          inspection — the runtime does NOT use
                          it as a re-entry trigger.
    """

    identity: SessionIdentity
    opened_at: datetime
    lifecycle: SessionLifecycle
    lineage: SessionLineage
    context: SessionContext | None = None
    sequence_head: int = -1
    revision: int = 0
    metadata_signature: tuple[tuple[str, str], ...] = field(
        default_factory=tuple
    )

    def __post_init__(self) -> None:
        if self.opened_at.tzinfo is None:
            raise ValueError(
                "OperationalSession.opened_at must be timezone-"
                "aware (UTC)"
            )
        if self.revision < 0:
            raise ValueError(
                "OperationalSession.revision must be non-negative"
            )
        if self.sequence_head < -1:
            raise ValueError(
                "OperationalSession.sequence_head must be >= -1"
            )
        if (
            self.lineage.session_id != self.identity.session_id
        ):
            raise ValueError(
                "OperationalSession.lineage.session_id must equal "
                "identity.session_id"
            )


__all__ = ["OperationalSession"]
