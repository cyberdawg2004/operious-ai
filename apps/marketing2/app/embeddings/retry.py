"""Embedding retry primitives.

The retry semantics required by the embedding gateway are identical
to those required by the AI gateway (bounded attempts, exponential
backoff, predicate-driven re-try). Rather than duplicate the helper,
this module re-exports the canonical primitives from `app.ai.retry`.

Sprint G's principle that "runtime cross-cutting concerns remain
centralized" is honoured by keeping a single implementation; the
re-export here keeps the embedding subsystem self-contained at the
import level.
"""

from app.ai.retry import AttemptCallback, RetryPolicy, retry_async

__all__ = ["RetryPolicy", "retry_async", "AttemptCallback"]
