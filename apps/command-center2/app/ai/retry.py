"""Bounded retry helper.

Deliberately hand-rolled and tiny. We don't pull in tenacity / backoff
because the semantics we need (max attempts, exponential backoff,
predicate-driven retry, optional per-attempt callback) fit in ~50 lines
of explicit code and the retry surface is something we want to audit,
not delegate.

`retry_async` is generic and *only* handles retry. Timeout enforcement
is intentionally NOT a concern of this module — callers wrap their
operation in whatever timeout primitive they prefer (the AI gateway
wraps each provider call in `asyncio.wait_for` itself, mapping the
result onto the typed `AIProviderError` hierarchy). Keeping the two
concerns separate is what lets the same helper serve provider
invocations today and other infrastructure calls (webhook delivery,
periodic probes) later without coupling.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Awaitable, Callable, TypeVar

T = TypeVar("T")

AttemptCallback = Callable[[int, BaseException | None], None]


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Retry envelope.

    Attributes:
        max_attempts:   Total attempts including the first one.
        backoff_base:   Initial sleep, in seconds.
        backoff_max:    Cap on sleep, in seconds. Exponential growth
                        saturates here.
    """

    max_attempts: int = 3
    backoff_base: float = 0.5
    backoff_max: float = 8.0


def _compute_delay(policy: RetryPolicy, attempt: int) -> float:
    delay = policy.backoff_base * (2 ** (attempt - 1))
    return min(delay, policy.backoff_max)


async def retry_async(
    *,
    operation: Callable[[], Awaitable[T]],
    policy: RetryPolicy,
    is_retryable: Callable[[BaseException], bool],
    on_attempt: AttemptCallback | None = None,
) -> T:
    """Run `operation` up to `policy.max_attempts` times.

    Behaviour:

    * After each attempt, `on_attempt(attempt_number, exc_or_None)` is
      invoked. `None` means the attempt succeeded.
    * If the attempt raised and `is_retryable(exc)` is True and we have
      attempts remaining, sleep then loop.
    * If the attempt raised and the predicate is False — or we ran out
      of attempts — the exception is re-raised.
    """
    if policy.max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")

    last_exc: BaseException | None = None
    for attempt in range(1, policy.max_attempts + 1):
        try:
            result = await operation()
        except BaseException as exc:  # noqa: BLE001 — retry layer must observe everything
            last_exc = exc
            if on_attempt is not None:
                on_attempt(attempt, exc)
            if attempt >= policy.max_attempts or not is_retryable(exc):
                raise
            await asyncio.sleep(_compute_delay(policy, attempt))
            continue

        if on_attempt is not None:
            on_attempt(attempt, None)
        return result

    # Unreachable: loop either returned or raised.
    assert last_exc is not None  # pragma: no cover
    raise last_exc


__all__ = ["RetryPolicy", "retry_async", "AttemptCallback"]
