"""Voice persistence records."""

from __future__ import annotations

from dataclasses import dataclass

from app.boundary.voice.models.identity_bundle import (
    VoiceIdentity,
)
from app.boundary.voice.models.lineage import (
    VoiceLineageEntry,
)
from app.boundary.voice.models.replay import VoiceReplay
from app.boundary.voice.models.synthesis import (
    VoiceSynthesis,
)
from app.boundary.voice.models.transcript import (
    VoiceTranscript,
)


@dataclass(frozen=True, slots=True)
class VoiceIngressRecord:
    """Write-once persistence record for one ingress STT event."""

    identity: VoiceIdentity
    transcript: VoiceTranscript
    lineage_entry: VoiceLineageEntry
    replay: VoiceReplay


@dataclass(frozen=True, slots=True)
class VoiceEgressRecord:
    """Write-once persistence record for one egress TTS event."""

    identity: VoiceIdentity
    synthesis: VoiceSynthesis
    lineage_entry: VoiceLineageEntry
    replay: VoiceReplay


__all__ = ["VoiceEgressRecord", "VoiceIngressRecord"]
