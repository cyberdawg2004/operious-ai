"""Never-raising envelopes for the boundary substrate.

Two envelope shapes mirror the runtime split:

* `BoundaryIngressEnvelope` — output of `BoundaryIngressRuntime.ingest()`.
* `BoundaryEgressEnvelope`  — output of `BoundaryEgressRuntime.emit()`.

Both are always-present trace + optional result + optional error.
Same semantics as every sibling substrate: a result-bearing
envelope is a successful call (the substrate produced an
interpretation); a `None` result with attached error is a
framework-level failure.

For ingress, a *result-bearing* envelope may still describe a
MALFORMED / UNAUTHENTICATED normalisation — that's a successful
substrate run interpreting a hostile external delivery, not a
boundary failure.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.boundary.contracts.results import (
    BoundaryEgressResult,
    BoundaryIngressResult,
)
from app.boundary.tracing import BoundaryTrace


@dataclass(frozen=True, slots=True)
class BoundaryIngressEnvelope:
    """Never-raising container around one ingest() outcome."""

    trace: BoundaryTrace
    result: BoundaryIngressResult | None = None
    error: BaseException | None = None

    @property
    def is_ok(self) -> bool:
        """True iff a result was produced (substrate succeeded)."""
        return self.result is not None

    @property
    def is_fully_clean(self) -> bool:
        return self.result is not None and self.error is None

    def unwrap(self) -> BoundaryIngressResult:
        if self.result is None:
            raise RuntimeError(
                "BoundaryIngressEnvelope.unwrap() called on a failed "
                "envelope; inspect .trace and .error first."
            ) from self.error
        return self.result


@dataclass(frozen=True, slots=True)
class BoundaryEgressEnvelope:
    """Never-raising container around one emit() outcome."""

    trace: BoundaryTrace
    result: BoundaryEgressResult | None = None
    error: BaseException | None = None

    @property
    def is_ok(self) -> bool:
        return self.result is not None

    @property
    def is_fully_clean(self) -> bool:
        return self.result is not None and self.error is None

    def unwrap(self) -> BoundaryEgressResult:
        if self.result is None:
            raise RuntimeError(
                "BoundaryEgressEnvelope.unwrap() called on a failed "
                "envelope; inspect .trace and .error first."
            ) from self.error
        return self.result


__all__ = ["BoundaryIngressEnvelope", "BoundaryEgressEnvelope"]
