"""`VoiceRuntime` — typed namespace combining ingress + egress."""

from __future__ import annotations

from app.boundary.voice.egress.runtime import VoiceEgressRuntime
from app.boundary.voice.ingress.runtime import (
    VoiceIngressRuntime,
)
from app.boundary.voice.persistence.repository import (
    VoicePersistenceProtocol,
)


class VoiceRuntime:
    """Composition root for the voice substrate."""

    __slots__ = ("_ingress", "_egress")

    def __init__(
        self,
        *,
        ingress: VoiceIngressRuntime,
        egress: VoiceEgressRuntime,
    ) -> None:
        self._ingress = ingress
        self._egress = egress

    @property
    def ingress(self) -> VoiceIngressRuntime:
        return self._ingress

    @property
    def egress(self) -> VoiceEgressRuntime:
        return self._egress

    @property
    def persistence(self) -> VoicePersistenceProtocol:
        if (
            self._ingress.persistence
            is not self._egress.persistence
        ):
            raise RuntimeError(
                "VoiceRuntime expects ingress + egress to share "
                "the same persistence backend"
            )
        return self._ingress.persistence


__all__ = ["VoiceRuntime"]
