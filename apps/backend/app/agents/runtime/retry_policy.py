"""Retry policy definitions per diagnostic error class."""

from __future__ import annotations

from dataclasses import dataclass

from app.queues import QUEUE_DEAD_LETTER, QUEUE_DIAGNOSTIC_RETRY


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_retries: int
    base_delay_seconds: int
    backoff_multiplier: float
    terminal: bool
    queue: str


RETRY_POLICIES: dict[str, RetryPolicy] = {
    "PROVIDER_429": RetryPolicy(
        max_retries=4,
        base_delay_seconds=60,
        backoff_multiplier=2.0,
        terminal=False,
        queue=QUEUE_DIAGNOSTIC_RETRY,
    ),
    "PROVIDER_5XX": RetryPolicy(
        max_retries=3,
        base_delay_seconds=30,
        backoff_multiplier=2.0,
        terminal=False,
        queue=QUEUE_DIAGNOSTIC_RETRY,
    ),
    "PARSING_FAILURE": RetryPolicy(
        max_retries=1,
        base_delay_seconds=10,
        backoff_multiplier=1.0,
        terminal=False,
        queue=QUEUE_DIAGNOSTIC_RETRY,
    ),
    "SEMANTIC_REJECTION": RetryPolicy(
        max_retries=0,
        base_delay_seconds=0,
        backoff_multiplier=1.0,
        terminal=True,
        queue=QUEUE_DEAD_LETTER,
    ),
    "GOVERNANCE_DENY": RetryPolicy(
        max_retries=0,
        base_delay_seconds=0,
        backoff_multiplier=1.0,
        terminal=True,
        queue=QUEUE_DEAD_LETTER,
    ),
    "PERSISTENCE_FAILURE": RetryPolicy(
        max_retries=3,
        base_delay_seconds=15,
        backoff_multiplier=2.0,
        terminal=False,
        queue=QUEUE_DIAGNOSTIC_RETRY,
    ),
    "QUOTA_EXCEEDED": RetryPolicy(
        max_retries=4,
        base_delay_seconds=60,
        backoff_multiplier=2.0,
        terminal=False,
        queue=QUEUE_DIAGNOSTIC_RETRY,
    ),
}

_DEFAULT_RETRY_POLICY = RetryPolicy(
    max_retries=2,
    base_delay_seconds=30,
    backoff_multiplier=2.0,
    terminal=False,
    queue=QUEUE_DIAGNOSTIC_RETRY,
)


def get_policy(error_class: str) -> RetryPolicy:
    return RETRY_POLICIES.get(error_class, _DEFAULT_RETRY_POLICY)


__all__ = ["RETRY_POLICIES", "RetryPolicy", "get_policy"]
