"""`VoiceIdentity` — replay-safe identity bundle for voice events."""

from __future__ import annotations

from dataclasses import dataclass

from app.boundary.voice.identity import (
    VoiceCorrelationId,
    VoiceEventId,
    VoiceLineageId,
)


@dataclass(frozen=True, slots=True)
class VoiceIdentity:
    """Replay-safe identity bundle attached to a voice event."""

    event_id: VoiceEventId
    lineage_id: VoiceLineageId
    correlation_id: VoiceCorrelationId
    seed: str
    request_id: str | None = None
    tenant_id: str | None = None

    def __post_init__(self) -> None:
        if not self.seed:
            raise ValueError(
                "VoiceIdentity.seed must be non-empty"
            )


__all__ = ["VoiceIdentity"]
