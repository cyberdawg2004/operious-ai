"""Turn-taking stubs for voice call sessions."""

from __future__ import annotations

import hashlib
from datetime import datetime

from app.boundary.voice.models.audio import VoiceAudioHandle


class SilenceDetector:
    """Stub VAD based on elapsed time since the last audio chunk."""

    SILENCE_TIMEOUT_MS: int = 800

    def is_utterance_complete(
        self,
        last_chunk_at: datetime,
        now: datetime,
    ) -> bool:
        elapsed = (now - last_chunk_at).total_seconds() * 1000
        return elapsed >= self.SILENCE_TIMEOUT_MS


class BargeinDetector:
    """Stub barge-in: any audio chunk during speaking interrupts."""

    def is_barge_in(
        self,
        call_state: object,
        audio_chunk: VoiceAudioHandle,
    ) -> bool:
        _ = audio_chunk
        return getattr(call_state, "value", call_state) == "speaking"


class ResponseBudget:
    """Deterministic filler phrase selector."""

    FILLER_THRESHOLD_MS: int = 700
    FILLER_PHRASES: list[str] = [
        "Let me check that for you.",
        "One moment while I look that up.",
        "I'm reviewing the warranty policy now.",
    ]

    def select_filler(self, session_context: dict[str, object]) -> str:
        session_id = str(session_context.get("session_id") or "")
        digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
        index = int(digest[:8], 16) % len(self.FILLER_PHRASES)
        return self.FILLER_PHRASES[index]


__all__ = [
    "BargeinDetector",
    "ResponseBudget",
    "SilenceDetector",
]
