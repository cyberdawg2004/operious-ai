"""Never-raising envelope for the intelligence substrate.

Every public runtime method returns one of these. Callers
inspect ``.is_ok`` / ``.result`` / ``.error`` instead of catching.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.organizational_intelligence.traces.trace import (
    IntelligenceTrace,
)


@dataclass(frozen=True, slots=True)
class IntelligenceEnvelope:
    """Outcome of one organizational-intelligence runtime call."""

    trace: IntelligenceTrace
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
                "IntelligenceEnvelope.unwrap() on a failed envelope; "
                "inspect .trace and .error first."
            ) from self.error
        return self.result


__all__ = ["IntelligenceEnvelope"]
