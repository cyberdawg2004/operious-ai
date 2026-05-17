"""Never-raising envelope for the session substrate.

A single typed envelope wraps every runtime call's outcome. Per
substrate convention:

* `trace`  — always present.
* `result` — typed-by-call-kind, optional. Populated when the
              substrate succeeded semantically.
* `error`  — optional. Populated when the framework itself
              failed (validation, persistence, lifecycle rejection).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeVar

from app.session.contracts.results import (
    AppendEventResult,
    OpenSessionResult,
    ReconstructSessionResult,
    RecordContextResult,
    RecordCorrelationResult,
    RecordLifecycleResult,
)
from app.session.traces.trace import SessionTrace

T = TypeVar(
    "T",
    OpenSessionResult,
    AppendEventResult,
    RecordLifecycleResult,
    RecordContextResult,
    RecordCorrelationResult,
    ReconstructSessionResult,
)


@dataclass(frozen=True, slots=True)
class SessionEnvelope:
    """Never-raising container around one runtime call.

    The `result` is one of the typed-result shapes (or ``None``
    when the framework rejected the call before it could produce
    one). The `error` is the captured exception (if any). Public
    runtime methods NEVER raise; callers inspect `.is_ok` /
    `.error` / `.result` instead.
    """

    trace: SessionTrace
    result: object | None = None
    error: BaseException | None = None

    @property
    def is_ok(self) -> bool:
        """True iff a result was produced (substrate succeeded)."""
        return self.result is not None

    @property
    def is_fully_clean(self) -> bool:
        return self.result is not None and self.error is None

    def unwrap(self) -> object:
        """Return the result or raise (for callers that prefer raise-style).

        ``unwrap()`` is **opt-in** — callers that adopt the
        substrate-convention never-raise semantics should inspect
        ``.is_ok`` / ``.result`` directly.
        """
        if self.result is None:
            raise RuntimeError(
                "SessionEnvelope.unwrap() called on a failed "
                "envelope; inspect .trace and .error first."
            ) from self.error
        return self.result


__all__ = ["SessionEnvelope"]
