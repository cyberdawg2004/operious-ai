"""`VoiceLineage` — append-only voice ancestry."""

from __future__ import annotations

from dataclasses import dataclass

from app.boundary.voice.enums import VoiceDirection
from app.boundary.voice.identity import (
    VoiceCorrelationId,
    VoiceLineageId,
)


@dataclass(frozen=True, slots=True)
class VoiceLineageEntry:
    """One immutable lineage entry."""

    sequence: int
    direction: VoiceDirection
    audio_fingerprint: str
    transcript_fingerprint: str | None
    provider_name: str
    seed: str

    def __post_init__(self) -> None:
        if self.sequence < 0:
            raise ValueError(
                "VoiceLineageEntry.sequence must be >= 0"
            )
        if not self.audio_fingerprint:
            raise ValueError(
                "VoiceLineageEntry.audio_fingerprint must be "
                "non-empty"
            )
        if not self.provider_name:
            raise ValueError(
                "VoiceLineageEntry.provider_name must be non-empty"
            )
        if not self.seed:
            raise ValueError(
                "VoiceLineageEntry.seed must be non-empty"
            )


@dataclass(frozen=True, slots=True)
class VoiceLineage:
    """Append-only lineage of voice events."""

    lineage_id: VoiceLineageId
    correlation_id: VoiceCorrelationId
    entries: tuple[VoiceLineageEntry, ...]

    def __post_init__(self) -> None:
        prev = -1
        for e in self.entries:
            if e.sequence <= prev:
                raise ValueError(
                    "VoiceLineage.entries must be strictly "
                    "monotonic by sequence"
                )
            prev = e.sequence


__all__ = ["VoiceLineage", "VoiceLineageEntry"]
