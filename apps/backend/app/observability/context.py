"""Request-scoped context variables.

`ContextVar` is the right primitive here: it propagates automatically
across `await` boundaries inside a single task and stays isolated
between concurrent requests. No middleware-state tricks, no
threadlocal hacks.

The accessors are deliberately read-only from the application layer.
Setting the values is the middleware's job, with the returned token
used to reset the value on the way out — that's what keeps the context
strictly per-request.
"""

from __future__ import annotations

from contextvars import ContextVar, Token

_REQUEST_ID: ContextVar[str | None] = ContextVar("operious_request_id", default=None)


def get_request_id() -> str | None:
    """Return the current request id, or `None` outside a request."""
    return _REQUEST_ID.get()


def set_request_id(request_id: str) -> Token[str | None]:
    """Bind a request id to the current task context.

    Returns the reset token; callers MUST call `reset_request_id(token)`
    in their `finally` block to keep the context clean.
    """
    return _REQUEST_ID.set(request_id)


def reset_request_id(token: Token[str | None]) -> None:
    """Restore the previous request id (or `None` if unset)."""
    _REQUEST_ID.reset(token)


__all__ = [
    "get_request_id",
    "set_request_id",
    "reset_request_id",
]
