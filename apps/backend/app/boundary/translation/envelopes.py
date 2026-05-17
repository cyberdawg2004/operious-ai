"""`TranslationEnvelope` — never-raising envelope."""

from __future__ import annotations

from dataclasses import dataclass

from app.boundary.translation.traces.trace import TranslationTrace


@dataclass(frozen=True, slots=True)
class TranslationEnvelope:
    """Outcome of one translation-runtime call.

    Public translation runtime methods always return a
    `TranslationEnvelope`. Errors are captured inside the
    envelope; never raised.
    """

    trace: TranslationTrace
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
                "TranslationEnvelope.unwrap() on a failed "
                "envelope; inspect .trace and .error first."
            ) from self.error
        return self.result


__all__ = ["TranslationEnvelope"]
