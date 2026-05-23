"""Execution envelopes.

`ExecutionEnvelope[T]` is the universal return shape of the AI gateway.
It always carries a `trace` — every execution is observable, even when
it failed — and either a `result` (on success) or an `error` (on
failure). Callers may branch on `is_ok` or call `unwrap()` for
exception-style flow.

Returning a uniform envelope rather than raising for failure has two
durable benefits:

1. Orchestration runtimes can fan out N inference calls in
   `asyncio.gather(...)` and inspect the trace of every one — including
   failed ones — without try/except gymnastics per branch.
2. Governance and analytics get the full picture: the same envelope
   describes both successful and failed executions in one shape.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

from app.ai.tracing import ExecutionTrace
from app.providers.exceptions import AIProviderError

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class ExecutionEnvelope(Generic[T]):
    """Result-or-error wrapper around one AI execution.

    Invariant: exactly one of (`result`, `error`) is populated. The
    `trace` is always present.
    """

    trace: ExecutionTrace
    result: T | None = None
    error: AIProviderError | None = None

    @property
    def is_ok(self) -> bool:
        return self.error is None and self.result is not None

    def unwrap(self) -> T:
        """Return the result or raise the captured error."""
        if self.error is not None:
            raise self.error
        if self.result is None:  # pragma: no cover — invariant violation
            raise RuntimeError("envelope has neither result nor error")
        return self.result


__all__ = ["ExecutionEnvelope"]
