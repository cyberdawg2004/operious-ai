"""`TranslationReplay` — replay-disposition record for translation events."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from app.boundary.translation.identity import TranslationReplayId


@dataclass(frozen=True, slots=True)
class TranslationReplay:
    """Immutable replay-disposition record.

    Captures the inputs and provider identity required to
    reconstruct a translation event without re-executing it.
    """

    replay_id: TranslationReplayId
    seed: str
    canonical_fingerprint: str
    boundary_fingerprint: str
    provider_name: str
    captured_at: datetime
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.seed:
            raise ValueError(
                "TranslationReplay.seed must be non-empty"
            )
        if not self.canonical_fingerprint:
            raise ValueError(
                "TranslationReplay.canonical_fingerprint must be "
                "non-empty"
            )
        if not self.boundary_fingerprint:
            raise ValueError(
                "TranslationReplay.boundary_fingerprint must be "
                "non-empty"
            )
        if not self.provider_name:
            raise ValueError(
                "TranslationReplay.provider_name must be non-empty"
            )
        if self.captured_at.tzinfo is None:
            raise ValueError(
                "TranslationReplay.captured_at must be tz-aware"
            )


__all__ = ["TranslationReplay"]
