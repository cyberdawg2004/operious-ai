"""`VoiceEnvelope` — never-raising envelope."""

from __future__ import annotations

from dataclasses import dataclass

from app.boundary.voice.traces.trace import VoiceTrace


@dataclass(frozen=True, slots=True)
class VoiceEnvelope:
    """Outcome of one voice-runtime call."""

    trace: VoiceTrace
    result: object | None = None
    error: BaseException | None = None

    @property
    def is_ok(self) -> bool:
        return self.result is not None

    @property
    def is_fully_clean(self) -> bool:
        return self.result is not None and self.error is None

    def unwrap(self) -> object:
        if self.result is None:
            raise RuntimeError(
                "VoiceEnvelope.unwrap() on a failed envelope; "
                "inspect .trace and .error first."
            ) from self.error
        return self.result


__all__ = ["VoiceEnvelope"]
