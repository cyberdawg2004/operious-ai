"""Voice-runtime results."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.boundary.voice.enums import VoiceStatus
from app.boundary.voice.models.identity_bundle import (
    VoiceIdentity,
)
from app.boundary.voice.models.replay import VoiceReplay
from app.boundary.voice.models.synthesis import (
    VoiceSynthesis,
)
from app.boundary.voice.models.transcript import (
    VoiceTranscript,
)


@dataclass(frozen=True, slots=True)
class _BaseResult:
    sequence: int
    runtime_instance_id: uuid.UUID
    started_at: datetime
    ended_at: datetime
    latency_ms: float
    status: VoiceStatus
    correlation_id: str | None = None
    request_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict[str, Any])


@dataclass(frozen=True, slots=True)
class IngressTranscribeResult(_BaseResult):
    identity: VoiceIdentity | None = None
    transcript: VoiceTranscript | None = None
    replay: VoiceReplay | None = None


@dataclass(frozen=True, slots=True)
class EgressSynthesizeResult(_BaseResult):
    identity: VoiceIdentity | None = None
    synthesis: VoiceSynthesis | None = None
    replay: VoiceReplay | None = None


__all__ = [
    "EgressSynthesizeResult",
    "IngressTranscribeResult",
]
