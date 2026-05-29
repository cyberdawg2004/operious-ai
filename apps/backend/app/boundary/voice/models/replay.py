"""`VoiceReplay` — replay disposition for voice events."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.boundary.voice.identity import VoiceReplayId


@dataclass(frozen=True, slots=True)
class VoiceReplay:
    """Immutable replay-disposition record."""

    replay_id: VoiceReplayId
    seed: str
    audio_fingerprint: str
    transcript_fingerprint: str | None
    provider_name: str
    captured_at: datetime
    attributes: dict[str, Any] = field(default_factory=dict[str, Any])

    def __post_init__(self) -> None:
        if not self.seed:
            raise ValueError(
                "VoiceReplay.seed must be non-empty"
            )
        if not self.audio_fingerprint:
            raise ValueError(
                "VoiceReplay.audio_fingerprint must be non-empty"
            )
        if not self.provider_name:
            raise ValueError(
                "VoiceReplay.provider_name must be non-empty"
            )
        if self.captured_at.tzinfo is None:
            raise ValueError(
                "VoiceReplay.captured_at must be tz-aware"
            )


__all__ = ["VoiceReplay"]
