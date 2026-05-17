"""`TranslationRuntime` — typed namespace combining ingress + egress."""

from __future__ import annotations

from app.boundary.translation.egress.runtime import (
    TranslationEgressRuntime,
)
from app.boundary.translation.ingress.runtime import (
    TranslationIngressRuntime,
)
from app.boundary.translation.persistence.repository import (
    TranslationPersistenceProtocol,
)


class TranslationRuntime:
    """Composition root for the translation substrate.

    The aggregator does NOT execute any orchestration. It is a
    typed namespace that exposes the two runtimes side by side.
    """

    __slots__ = ("_ingress", "_egress")

    def __init__(
        self,
        *,
        ingress: TranslationIngressRuntime,
        egress: TranslationEgressRuntime,
    ) -> None:
        self._ingress = ingress
        self._egress = egress

    @property
    def ingress(self) -> TranslationIngressRuntime:
        return self._ingress

    @property
    def egress(self) -> TranslationEgressRuntime:
        return self._egress

    @property
    def persistence(self) -> TranslationPersistenceProtocol:
        if (
            self._ingress.persistence
            is not self._egress.persistence
        ):
            raise RuntimeError(
                "TranslationRuntime expects ingress + egress to "
                "share the same persistence backend"
            )
        return self._ingress.persistence


__all__ = ["TranslationRuntime"]
