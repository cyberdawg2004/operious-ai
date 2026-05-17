"""Never-raising envelope for the hardening substrate."""

from __future__ import annotations

from dataclasses import dataclass

from app.hardening.traces.trace import HardeningTrace


@dataclass(frozen=True, slots=True)
class HardeningEnvelope:
    """Outcome of one hardening-runtime call."""

    trace: HardeningTrace
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
                "HardeningEnvelope.unwrap() on a failed envelope; "
                "inspect .trace and .error first."
            ) from self.error
        return self.result


__all__ = ["HardeningEnvelope"]
